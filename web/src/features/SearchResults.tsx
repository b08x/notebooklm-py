import { AlertTriangle, SearchX } from "lucide-react";
import { useMemo } from "react";
import { Checkbox } from "@/components/ui/checkbox";
import { Highlight } from "@/lib/highlight";
import type { SearchHit, SearchResult } from "@/lib/types";
import { cn, fmt } from "@/lib/utils";
import { RowMeta } from "./RowMeta";
import { ScoreBars } from "./ScoreBars";

interface Props {
  result: SearchResult | undefined;
  loading: boolean;
  query: string;
  selected: string[];
  cursor: string | null;
  detailId: string | null;
  hidden: string[];
  onOpen: (id: string) => void;
  onToggle: (id: string, shift: boolean) => void;
  header?: React.ReactNode;
}

export function ResultRow({
  hit,
  query,
  maxScore,
  depth,
  selected,
  active,
  focused,
  onOpen,
  onToggle,
}: {
  hit: SearchHit;
  query: string;
  maxScore: number;
  depth: number;
  selected: boolean;
  active: boolean;
  focused: boolean;
  onOpen: (id: string) => void;
  onToggle: (id: string, shift: boolean) => void;
}) {
  const noisy = hit.quality !== "clean";
  return (
    <div
      role="row"
      aria-selected={active}
      data-row-id={hit.external_id}
      data-testid="result-row"
      onClick={() => onOpen(hit.external_id)}
      className={cn(
        "grid cursor-default grid-cols-[18px_minmax(0,1fr)_136px] gap-3 border-b border-line/70 px-3.5 py-3 transition-[background-color] duration-150 hover:bg-surface/60",
        active && "bg-selection shadow-[inset_2px_0_0_var(--primary)]",
        focused && !active && "bg-surface/80",
        noisy && "opacity-75",
      )}
    >
      <span className="pt-0.5" onClick={(e) => e.stopPropagation()}>
        <Checkbox
          checked={selected}
          aria-label="Select chunk"
          onClick={(e) => {
            e.preventDefault();
            onToggle(hit.external_id, e.shiftKey);
          }}
        />
      </span>
      <div className="min-w-0">
        <p
          className={cn(
            "mb-1.5 line-clamp-3 text-[13.5px] leading-[1.5] break-words text-pretty",
            noisy && "font-mono text-[12px] break-all text-muted",
          )}
        >
          <Highlight text={hit.text} query={query} />
        </p>
        <RowMeta row={hit} />
      </div>
      <ScoreBars kwRank={hit.kw_rank} vecRank={hit.vec_rank} score={hit.score} maxScore={maxScore} depth={depth} />
    </div>
  );
}

export function SearchResults({ result, loading, query, selected, cursor, detailId, hidden, onOpen, onToggle, header }: Props) {
  const hits = useMemo(() => (result?.hits ?? []).filter((h) => !hidden.includes(h.external_id)), [result, hidden]);
  const maxScore = hits.reduce((m, h) => Math.max(m, h.score), 0);
  const depth = Math.max(result?.keyword_count ?? 0, result?.vector_count ?? 0, 1);

  if (!query.trim()) {
    return (
      <div className="grid flex-1 place-items-center p-8 text-center text-muted">
        <div className="max-w-sm">
          <p className="mb-1 text-[14px] text-fg">Search the corpus</p>
          <p className="text-[12.5px]">
            Hybrid search fuses keyword and vector rankings with RRF. Press <kbd className="font-mono">/</kbd> to start typing.
          </p>
        </div>
      </div>
    );
  }
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex items-center gap-2.5 border-b border-line px-3.5 py-2.5 text-[12px] text-muted">
        <span className="tabular">
          {loading && !result ? "Searching…" : `${fmt.format(hits.length)} results · ${result?.elapsed_ms ?? 0} ms`}
        </span>
        <span>sorted by fused score</span>
        {header}
      </div>
      {result && !result.vector_leg_ok && (
        <div role="alert" className="flex items-center gap-2 border-b border-line bg-warn/10 px-3.5 py-2 text-[12.5px] text-warn">
          <AlertTriangle className="size-3.5" />
          Vector leg unavailable — the embedder is down, showing keyword results only.
        </div>
      )}
      <div role="grid" aria-label="Search results" className="min-h-0 flex-1 overflow-auto">
        {hits.map((hit) => (
          <ResultRow
            key={hit.external_id}
            hit={hit}
            query={query}
            maxScore={maxScore}
            depth={depth}
            selected={selected.includes(hit.external_id)}
            active={detailId === hit.external_id}
            focused={cursor === hit.external_id}
            onOpen={onOpen}
            onToggle={onToggle}
          />
        ))}
        {result && hits.length === 0 && (
          <div className="grid place-items-center gap-2 p-10 text-center text-muted">
            <SearchX className="size-5" />
            <p className="text-[13px]">No chunks match “{query}”.</p>
          </div>
        )}
      </div>
    </div>
  );
}
