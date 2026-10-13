import { useVirtualizer } from "@tanstack/react-virtual";
import {
  ChevronDown,
  ChevronRight,
  ChevronsDownUp,
  ChevronsUpDown,
  Filter,
} from "lucide-react";
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { useDocumentClauses, useDocuments } from "@/lib/queries";
import type { DocumentClauseItem, DocumentItem } from "@/lib/types";
import { cn } from "@/lib/utils";
import { actions, useApp } from "@/state/store";

export interface ChunkGroup {
  parentId: number | null;
  chunkIndex: number;
  clauses: DocumentClauseItem[];
  taggedCount: number;
  factCheckedCount: number;
  hasFlags: boolean;
}

export function getVerdict(c: DocumentClauseItem): "supported" | "unverified" | "contradicted" | null {
  const v = (c.latest_fact_check?.verdict || c.fact_check || "").toLowerCase();
  if (v === "supported" || v === "passed") return "supported";
  if (v === "unverified" || v === "warning") return "unverified";
  if (v === "contradicted" || v === "failed") return "contradicted";
  return null;
}

export function getStorageKey(docId: string): string {
  return `corpus-explorer:doc-collapsed:${docId}`;
}

export function loadCollapsedChunks(docId: string): Set<number> {
  if (typeof window === "undefined" || !docId) return new Set();
  try {
    const raw = localStorage.getItem(getStorageKey(docId));
    if (!raw) return new Set();
    const arr = JSON.parse(raw);
    return new Set(Array.isArray(arr) ? arr : []);
  } catch {
    return new Set();
  }
}

export function saveCollapsedChunks(docId: string, set: Set<number>): void {
  if (typeof window === "undefined" || !docId) return;
  try {
    localStorage.setItem(getStorageKey(docId), JSON.stringify(Array.from(set)));
  } catch {
    // Ignore storage errors
  }
}

export interface DocumentViewProps {
  documentId?: string | null;
}

export function DocumentView({ documentId }: DocumentViewProps = {}) {
  const storeDocId = useApp((s) => s.filters.document_ids?.[0] ?? null);
  const selectedDocId = documentId ?? storeDocId;
  const selectedClauseId = useApp((s) => s.detailId);

  const { data: docData, isLoading: docsLoading } = useDocuments();
  const { data: clausesData, isLoading: clausesLoading } = useDocumentClauses(selectedDocId);

  const currentDoc = useMemo(() => {
    const docs = (docData?.documents ?? docData?.items ?? []) as DocumentItem[];
    return docs.find((d) => (d.id || d.document_id) === selectedDocId);
  }, [docData, selectedDocId]);

  const clauses = useMemo<DocumentClauseItem[]>(() => {
    if (clausesData?.clauses && clausesData.clauses.length > 0) {
      return clausesData.clauses;
    }
    if (clausesData?.chunks && clausesData.chunks.length > 0) {
      return clausesData.chunks.flatMap((ch) => ch.clauses || []);
    }
    return [];
  }, [clausesData]);

  // Group clauses by parent chunk
  const chunks = useMemo<ChunkGroup[]>(() => {
    if (!clauses.length) return [];
    const groups: ChunkGroup[] = [];
    let currentGroup: ChunkGroup | null = null;

    for (const c of clauses) {
      if (!currentGroup || currentGroup.parentId !== c.parent_id) {
        currentGroup = {
          parentId: c.parent_id,
          chunkIndex: groups.length,
          clauses: [],
          taggedCount: 0,
          factCheckedCount: 0,
          hasFlags: false,
        };
        groups.push(currentGroup);
      }
      currentGroup.clauses.push(c);
      const isTagged = c.has_sfl || !!c.sfl_data || c.sfl_status === "tagged";
      if (isTagged) currentGroup.taggedCount += 1;

      const verdict = getVerdict(c);
      if (verdict) {
        currentGroup.factCheckedCount += 1;
        if (verdict === "contradicted" || verdict === "unverified") {
          currentGroup.hasFlags = true;
        }
      }
    }
    return groups;
  }, [clauses]);

  // Collapsed chunks state (persisted per document)
  const [collapsed, setCollapsed] = useState<Set<number>>(() =>
    selectedDocId ? loadCollapsedChunks(selectedDocId) : new Set(),
  );

  useEffect(() => {
    if (selectedDocId) {
      setCollapsed(loadCollapsedChunks(selectedDocId));
    }
  }, [selectedDocId]);

  const updateCollapsed = useCallback(
    (updater: (prev: Set<number>) => Set<number>) => {
      setCollapsed((prev) => {
        const next = updater(prev);
        if (selectedDocId) saveCollapsedChunks(selectedDocId, next);
        return next;
      });
    },
    [selectedDocId],
  );

  const toggleChunk = useCallback(
    (chunkIndex: number) => {
      updateCollapsed((prev) => {
        const next = new Set(prev);
        if (next.has(chunkIndex)) next.delete(chunkIndex);
        else next.add(chunkIndex);
        return next;
      });
    },
    [updateCollapsed],
  );

  const collapseAll = useCallback(() => {
    updateCollapsed(() => new Set(chunks.map((c) => c.chunkIndex)));
  }, [chunks, updateCollapsed]);

  const expandAll = useCallback(() => {
    updateCollapsed(() => new Set());
  }, [updateCollapsed]);

  const collapseUnflagged = useCallback(() => {
    updateCollapsed(() => {
      const next = new Set<number>();
      for (const c of chunks) {
        if (!c.hasFlags) {
          next.add(c.chunkIndex);
        }
      }
      return next;
    });
  }, [chunks, updateCollapsed]);

  const parentRef = useRef<HTMLDivElement>(null);

  const virtualizer = useVirtualizer({
    count: chunks.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => 140,
    overscan: 5,
  });

  // Flat list of visible clauses for keyboard arrow navigation
  const visibleClauses = useMemo(() => {
    const list: DocumentClauseItem[] = [];
    for (const chunk of chunks) {
      if (collapsed.has(chunk.chunkIndex)) {
        // Collapsed chunks only expose their first clause
        if (chunk.clauses[0]) list.push(chunk.clauses[0]);
      } else {
        list.push(...chunk.clauses);
      }
    }
    return list;
  }, [chunks, collapsed]);

  // Handle arrow key navigation: Up and Down skip collapsed clauses
  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
      if (!visibleClauses.length) return;

      e.preventDefault();
      const currentIndex = visibleClauses.findIndex(
        (c) => c.id === selectedClauseId || c.external_id === selectedClauseId,
      );

      let nextIndex = 0;
      if (e.key === "ArrowDown") {
        nextIndex = currentIndex >= 0 ? Math.min(visibleClauses.length - 1, currentIndex + 1) : 0;
      } else if (e.key === "ArrowUp") {
        nextIndex = currentIndex >= 0 ? Math.max(0, currentIndex - 1) : visibleClauses.length - 1;
      }

      const nextClause = visibleClauses[nextIndex];
      if (nextClause) {
        actions.open(nextClause.external_id || nextClause.id);
        // Scroll into view if needed
        const chunkIndex = chunks.findIndex((ch) =>
          ch.clauses.some((c) => c.id === nextClause.id || c.external_id === nextClause.external_id),
        );
        if (chunkIndex >= 0) {
          virtualizer.scrollToIndex(chunkIndex, { align: "auto" });
        }
      }
    },
    [visibleClauses, selectedClauseId, chunks, virtualizer],
  );

  const handleSelectClause = useCallback((c: DocumentClauseItem) => {
    actions.open(c.external_id || c.id);
  }, []);

  // Jump from marker strip
  const handleMarkerClick = useCallback(
    (chunkIndex: number, clauseId: string) => {
      // Expand chunk if collapsed
      if (collapsed.has(chunkIndex)) {
        updateCollapsed((prev) => {
          const next = new Set(prev);
          next.delete(chunkIndex);
          return next;
        });
      }
      virtualizer.scrollToIndex(chunkIndex, { align: "start" });
      actions.open(clauseId);
    },
    [collapsed, updateCollapsed, virtualizer],
  );

  if (!selectedDocId) {
    return (
      <div
        data-testid="document-view-empty"
        className="flex-1 flex flex-col items-center justify-center text-center p-8 text-muted"
      >
        <p className="text-[14px]">Select a document from the list to begin review.</p>
      </div>
    );
  }

  if (docsLoading || clausesLoading) {
    return (
      <div className="flex-1 flex items-center justify-center text-[13px] text-muted p-8">
        Loading document…
      </div>
    );
  }

  if (!currentDoc) {
    return (
      <div
        data-testid="document-view-empty"
        className="flex-1 flex flex-col items-center justify-center text-center p-8 text-muted"
      >
        <p className="text-[14px]">Select a document from the list to begin review.</p>
      </div>
    );
  }

  return (
    <div
      tabIndex={0}
      onKeyDown={handleKeyDown}
      data-testid="document-view"
      className="flex min-w-0 flex-1 flex-col overflow-hidden bg-bg relative outline-none select-text"
      aria-label="Document view"
    >
      {/* Document View Header */}
      <header className="flex h-12 shrink-0 items-center justify-between border-b border-line px-6 bg-surface z-10">
        <div className="flex min-w-0 items-center gap-3">
          <h2
            data-testid="document-title"
            className="text-[15px] font-semibold text-fg truncate"
            title={currentDoc.title}
          >
            {currentDoc.title}
          </h2>
          <span className="shrink-0 rounded bg-line px-1.5 py-0.5 font-mono text-[10px] uppercase text-muted">
            {currentDoc.file_type}
          </span>
          <span className="text-[12px] text-muted">
            {clauses.length} clauses
          </span>
        </div>

        {/* Controls: Collapse all, Collapse unflagged, Expand all */}
        <div className="flex items-center gap-1.5 shrink-0">
          <Button
            variant="ghost"
            size="sm"
            data-testid="collapse-all-btn"
            onClick={collapseAll}
            className="h-7 px-2 text-[11.5px] text-muted hover:text-fg gap-1 active:scale-[0.96]"
          >
            <ChevronsDownUp className="size-3.5" />
            Collapse all
          </Button>
          <Button
            variant="ghost"
            size="sm"
            data-testid="collapse-unflagged-btn"
            onClick={collapseUnflagged}
            className="h-7 px-2 text-[11.5px] text-muted hover:text-fg gap-1 active:scale-[0.96]"
          >
            <Filter className="size-3.5" />
            Collapse unflagged
          </Button>
          <Button
            variant="ghost"
            size="sm"
            data-testid="expand-all-btn"
            onClick={expandAll}
            className="h-7 px-2 text-[11.5px] text-muted hover:text-fg gap-1 active:scale-[0.96]"
          >
            <ChevronsUpDown className="size-3.5" />
            Expand all
          </Button>
        </div>
      </header>

      {/* Main Content Area with Virtualized Reading Column and Right-edge Marker Strip */}
      <div className="flex min-h-0 min-w-0 flex-1 relative overflow-hidden">
        {/* Reading Text Scroll Container */}
        <div
          ref={parentRef}
          data-testid="document-view-scroll"
          className="flex-1 overflow-y-auto overflow-x-hidden p-6 pr-12 min-w-0"
        >
          {clauses.length === 0 ? (
            <div className="p-8 text-center text-[13px] text-muted">
              This document contains no clauses.
            </div>
          ) : (
            <div
              style={{
                height: `${virtualizer.getTotalSize()}px`,
                width: "100%",
                position: "relative",
              }}
            >
              {virtualizer.getVirtualItems().map((vItem) => {
                const chunk = chunks[vItem.index];
                if (!chunk) return null;
                const isCollapsed = collapsed.has(chunk.chunkIndex);

                return (
                  <section
                    key={`chunk-${chunk.chunkIndex}`}
                    ref={virtualizer.measureElement}
                    data-index={vItem.index}
                    data-testid={`chunk-section-${chunk.chunkIndex}`}
                    style={{
                      position: "absolute",
                      top: 0,
                      left: 0,
                      width: "100%",
                      transform: `translateY(${vItem.start}px)`,
                    }}
                    className="mb-6 last:mb-0"
                  >
                    {/* Chunk Header */}
                    <div className="mb-2 flex items-center gap-2 text-[11px] font-mono text-muted border-b border-line/60 pb-1">
                      <button
                        type="button"
                        data-testid={`chunk-header-toggle-${chunk.chunkIndex}`}
                        onClick={() => toggleChunk(chunk.chunkIndex)}
                        aria-expanded={!isCollapsed}
                        className="flex items-center gap-1.5 hover:text-fg transition-[color,scale] duration-150 active:scale-[0.98]"
                      >
                        {isCollapsed ? (
                          <ChevronRight className="size-3 text-muted shrink-0" />
                        ) : (
                          <ChevronDown className="size-3 text-muted shrink-0" />
                        )}
                        <span className="font-semibold text-fg">
                          Chunk {chunk.chunkIndex + 1}
                        </span>
                      </button>

                      <span>·</span>
                      <span>{chunk.clauses.length} cls</span>
                      <span>·</span>
                      <span>{chunk.taggedCount} tagged</span>
                      <span>·</span>
                      <span>{chunk.factCheckedCount} checked</span>
                    </div>

                    {/* Chunk Body (Prose capped at 72ch) */}
                    <div
                      data-testid="chunk-body"
                      className="max-w-[72ch] text-[14px] leading-[1.5] text-fg font-sans space-y-1"
                    >
                      {isCollapsed ? (
                        // Collapsed: show first clause line + ellipsis
                        <p className="truncate text-muted italic">
                          {chunk.clauses[0]?.text ?? "Empty chunk"}
                        </p>
                      ) : (
                        // Expanded: inline clauses
                        <p className="inline leading-[1.6]">
                          {chunk.clauses.map((clause) => {
                            const isSelected =
                              selectedClauseId === clause.id ||
                              selectedClauseId === clause.external_id;
                            const isTagged =
                              clause.has_sfl || !!clause.sfl_data || clause.sfl_status === "tagged";
                            const verdict = getVerdict(clause);

                            return (
                              <React.Fragment key={clause.id}>
                                {verdict && (
                                  <span
                                    data-testid={`verdict-marker-${clause.id}`}
                                    aria-label={`Verdict: ${verdict}`}
                                    className={cn(
                                      "inline-block size-2 rounded-full mr-1.5 align-middle shrink-0 transition-transform duration-150",
                                      verdict === "supported" && "bg-ok",
                                      verdict === "unverified" && "bg-warn",
                                      verdict === "contradicted" && "bg-bad",
                                    )}
                                    title={`Fact-check: ${verdict}`}
                                  />
                                )}
                                <span
                                  data-testid={`clause-span-${clause.id}`}
                                  onClick={() => handleSelectClause(clause)}
                                  className={cn(
                                    "cursor-pointer rounded-[2px] transition-[background-color,box-shadow,color] duration-150 px-0.5",
                                    isTagged && "bg-primary/10 text-fg hover:bg-primary/20",
                                    isSelected
                                      ? "bg-primary/25 text-fg ring-1 ring-primary/60 shadow-xs font-medium"
                                      : !isTagged && "hover:bg-surface-2",
                                  )}
                                >
                                  {clause.text}{" "}
                                </span>
                              </React.Fragment>
                            );
                          })}
                        </p>
                      )}
                    </div>
                  </section>
                );
              })}
            </div>
          )}
        </div>

        {/* Right-edge Marker Strip */}
        <aside
          aria-label="Document marker strip"
          data-testid="marker-strip"
          className="absolute right-0 top-0 bottom-0 w-4 border-l border-line/40 bg-surface/30 select-none flex flex-col justify-between"
        >
          {clauses.map((clause, idx) => {
            const isTagged = clause.has_sfl || !!clause.sfl_data || clause.sfl_status === "tagged";
            const verdict = getVerdict(clause);
            if (!isTagged && !verdict) return null;

            const percent = (idx / Math.max(1, clauses.length - 1)) * 100;
            const chunkIndex = chunks.findIndex((ch) =>
              ch.clauses.some((c) => c.id === clause.id),
            );

            let markerColor = "bg-primary";
            if (verdict === "contradicted") markerColor = "bg-bad";
            else if (verdict === "unverified") markerColor = "bg-warn";
            else if (verdict === "supported") markerColor = "bg-ok";

            return (
              <button
                key={`marker-${clause.id}`}
                type="button"
                data-testid={`marker-tick-${clause.id}`}
                onClick={() => handleMarkerClick(chunkIndex, clause.external_id || clause.id)}
                aria-label={`Jump to clause ${idx + 1}`}
                style={{ top: `${percent}%` }}
                className={cn(
                  "absolute left-0.5 right-0.5 h-1 rounded-[1px] transition-transform duration-150 hover:scale-125 hover:z-20",
                  markerColor,
                )}
                title={`Clause ${idx + 1}: ${verdict || "tagged"}`}
              />
            );
          })}
        </aside>
      </div>
    </div>
  );
}
