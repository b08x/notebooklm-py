import { useVirtualizer } from "@tanstack/react-virtual";
import { ChevronDown, ChevronRight, FileText, Search } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useDocuments } from "@/lib/queries";
import type { DocumentItem } from "@/lib/types";
import { cn } from "@/lib/utils";
import { actions, store, useApp } from "@/state/store";

export const COLLAPSED_COLLECTIONS_KEY = "corpus-explorer:collapsed-collections";

export type DocumentFilterTab = "all" | "untagged" | "tagged" | "factchecked";

export function getInitialCollapsedCollections(): Set<string> {
  if (typeof window === "undefined") return new Set();
  try {
    const raw = localStorage.getItem(COLLAPSED_COLLECTIONS_KEY);
    if (!raw) return new Set();
    const parsed = JSON.parse(raw);
    return new Set(Array.isArray(parsed) ? parsed : []);
  } catch {
    return new Set();
  }
}

export function saveCollapsedCollections(collapsed: Set<string>): void {
  if (typeof window === "undefined") return;
  try {
    localStorage.setItem(COLLAPSED_COLLECTIONS_KEY, JSON.stringify(Array.from(collapsed)));
  } catch {
    // Ignore storage quota or disabled errors
  }
}

type VirtualRow =
  | { type: "header"; collectionId: string; title: string; count: number }
  | { type: "doc"; doc: DocumentItem };

interface DocumentListProps {
  className?: string;
  onSelectDoc?: () => void;
}

export function DocumentList({ className, onSelectDoc }: DocumentListProps) {
  const selectedDocId = useApp((s) => s.filters.document_ids?.[0]);
  const filters = useApp((s) => s.filters);
  const [search, setSearch] = useState("");
  const [filterTab, setFilterTab] = useState<DocumentFilterTab>("all");
  const [collapsedCollections, setCollapsedCollections] = useState<Set<string>>(
    getInitialCollapsedCollections,
  );

  const { data, isLoading } = useDocuments();
  const documents = (data?.documents ?? data?.items ?? []) as DocumentItem[];

  const toggleCollection = (collectionId: string) => {
    setCollapsedCollections((prev) => {
      const next = new Set(prev);
      if (next.has(collectionId)) {
        next.delete(collectionId);
      } else {
        next.add(collectionId);
      }
      saveCollapsedCollections(next);
      return next;
    });
  };

  // Filter documents
  const filteredDocs = useMemo(() => {
    return documents.filter((doc) => {
      // Search filter
      if (search.trim()) {
        const q = search.toLowerCase();
        const matchTitle = doc.title.toLowerCase().includes(q);
        const matchCollection = (doc.collection_title || "").toLowerCase().includes(q);
        if (!matchTitle && !matchCollection) return false;
      }

      // Tab filter
      if (filterTab === "untagged" && doc.tagged_count > 0) return false;
      if (filterTab === "tagged" && doc.tagged_count === 0) return false;
      if (filterTab === "factchecked" && doc.fact_checked_count === 0) return false;

      return true;
    });
  }, [documents, search, filterTab]);

  // Group by collection
  const groups = useMemo(() => {
    const map = new Map<string, { id: string; title: string; docs: DocumentItem[] }>();
    for (const doc of filteredDocs) {
      const collId = doc.collection_id || "uncategorized";
      const collTitle = doc.collection_title || "Uncategorized";
      let group = map.get(collId);
      if (!group) {
        group = { id: collId, title: collTitle, docs: [] };
        map.set(collId, group);
      }
      group.docs.push(doc);
    }
    return Array.from(map.values());
  }, [filteredDocs]);

  // Flatten for virtualization
  const virtualRows = useMemo(() => {
    const rows: VirtualRow[] = [];
    for (const group of groups) {
      rows.push({
        type: "header",
        collectionId: group.id,
        title: group.title,
        count: group.docs.length,
      });
      const isCollapsed = collapsedCollections.has(group.id);
      if (!isCollapsed) {
        for (const doc of group.docs) {
          rows.push({ type: "doc", doc });
        }
      }
    }
    return rows;
  }, [groups, collapsedCollections]);

  const parentRef = useRef<HTMLDivElement>(null);

  const virtualizer = useVirtualizer({
    count: virtualRows.length,
    getScrollElement: () => parentRef.current,
    estimateSize: (index) => {
      const row = virtualRows[index];
      return row?.type === "header" ? 32 : 40;
    },
    overscan: 10,
  });

  // Select first document automatically if none selected and documents available
  useEffect(() => {
    if (!selectedDocId && documents.length > 0) {
      const firstId = documents[0].id || documents[0].document_id;
      if (firstId) {
        actions.setFilters({ ...filters, document_ids: [firstId] });
      }
    }
  }, [documents, selectedDocId, filters]);

  const handleSelectDocument = (docId: string) => {
    actions.setFilters({ ...filters, document_ids: [docId] });
    actions.open(null);
    store.set({ listDrawerOpen: false });
    onSelectDoc?.();
  };

  return (
    <aside
      aria-label="Document list"
      data-testid="document-list"
      className={cn(
        "flex w-[320px] min-w-[320px] max-w-[320px] shrink-0 flex-col border-r border-line bg-surface select-none h-full overflow-hidden",
        className,
      )}
    >
      {/* Search Input */}
      <div className="p-2 border-b border-line">
        <div className="relative flex items-center">
          <Search className="pointer-events-none absolute left-2.5 size-3.5 text-muted" />
          <input
            type="search"
            data-testid="document-search-input"
            aria-label="Filter documents by title"
            placeholder="Filter documents…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="h-8 w-full rounded-lg bg-surface-2 pl-8 pr-2.5 text-[12px] text-fg outline-none placeholder:text-muted focus:ring-1 focus:ring-primary shadow-[inset_0_0_0_1px_var(--line)]"
          />
        </div>

        {/* Filter Tabs */}
        <div
          role="tablist"
          aria-label="Document filters"
          className="mt-2 flex rounded-lg bg-surface-2 p-0.5 text-[11px] shadow-[inset_0_0_0_1px_var(--line)]"
        >
          {(
            [
              { id: "all", label: "All" },
              { id: "untagged", label: "Untagged" },
              { id: "tagged", label: "Tagged" },
              { id: "factchecked", label: "Fact-checked" },
            ] as const
          ).map((tab) => {
            const active = filterTab === tab.id;
            return (
              <button
                key={tab.id}
                role="tab"
                type="button"
                data-testid={`document-filter-${tab.id}`}
                aria-selected={active}
                onClick={() => setFilterTab(tab.id)}
                className={cn(
                  "flex-1 rounded-md py-1 text-center font-medium transition-[color,background-color,scale] duration-150 active:scale-[0.96]",
                  active ? "bg-surface text-fg shadow-xs" : "text-muted hover:text-fg",
                )}
              >
                {tab.label}
              </button>
            );
          })}
        </div>
      </div>

      {/* Document & Collection List */}
      <div
        ref={parentRef}
        data-testid="document-list-scroll"
        className="flex-1 overflow-y-auto overflow-x-hidden min-h-0"
      >
        {isLoading ? (
          <div className="p-4 text-center text-[12px] text-muted">Loading documents…</div>
        ) : virtualRows.length === 0 ? (
          <div className="p-4 text-center text-[12px] text-muted">
            {search.trim() ? "No matching documents" : "No documents in corpus"}
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
              const row = virtualRows[vItem.index];
              if (!row) return null;

              if (row.type === "header") {
                const isCollapsed = collapsedCollections.has(row.collectionId);
                return (
                  <div
                    key={`header-${row.collectionId}`}
                    data-index={vItem.index}
                    data-testid={`collection-group-${row.collectionId}`}
                    style={{
                      position: "absolute",
                      top: 0,
                      left: 0,
                      width: "100%",
                      height: `${vItem.size}px`,
                      transform: `translateY(${vItem.start}px)`,
                    }}
                    className="flex items-center px-2 bg-surface border-b border-line text-[11px] font-semibold text-subtle uppercase tracking-wider"
                  >
                    <button
                      type="button"
                      data-testid={`collection-toggle-${row.collectionId}`}
                      onClick={() => toggleCollection(row.collectionId)}
                      aria-expanded={!isCollapsed}
                      className="flex items-center gap-1.5 w-full py-1 text-left hover:text-fg active:scale-[0.98] transition-[color,scale] duration-150"
                    >
                      {isCollapsed ? (
                        <ChevronRight className="size-3.5 text-muted shrink-0" />
                      ) : (
                        <ChevronDown className="size-3.5 text-muted shrink-0" />
                      )}
                      <span className="truncate">
                        Collection: {row.title}
                      </span>
                      <span className="ml-auto text-muted font-normal lowercase tracking-normal">
                        ({row.count})
                      </span>
                    </button>
                  </div>
                );
              }

              const doc = row.doc;
              const docId = doc.id || doc.document_id || "";
              const isSelected = selectedDocId === docId;
              const taggedPercent =
                doc.clause_count > 0 ? Math.round((doc.tagged_count / doc.clause_count) * 100) : 0;

              return (
                <div
                  key={`doc-${docId}`}
                  data-index={vItem.index}
                  style={{
                    position: "absolute",
                    top: 0,
                    left: 0,
                    width: "100%",
                    height: `${vItem.size}px`,
                    transform: `translateY(${vItem.start}px)`,
                  }}
                  className="px-1.5 py-0.5"
                >
                  <button
                    type="button"
                    data-testid={`doc-card-${docId}`}
                    aria-selected={isSelected}
                    onClick={() => handleSelectDocument(docId)}
                    className={cn(
                      "flex w-full h-[38px] flex-col justify-center rounded-lg px-2 text-left transition-[color,background-color,box-shadow,scale] duration-150 active:scale-[0.98]",
                      isSelected
                        ? "bg-surface-2 text-fg shadow-xs ring-1 ring-primary/40 font-medium"
                        : "text-muted hover:bg-surface-2/60 hover:text-fg",
                    )}
                  >
                    <div className="flex items-center gap-1.5 text-[13px] leading-tight truncate">
                      <FileText className="size-3.5 shrink-0 text-muted" />
                      <span className="truncate font-medium text-fg flex-1">{doc.title}</span>
                      <span className="shrink-0 rounded bg-line px-1 py-0.5 font-mono text-[9.5px] uppercase text-muted">
                        {doc.file_type}
                      </span>
                    </div>
                    <div className="flex items-center gap-2 text-[10.5px] text-muted leading-none mt-0.5 pl-5">
                      <span>{doc.clause_count} cls</span>
                      <span>·</span>
                      <span>{taggedPercent}% tagged</span>
                      <span>·</span>
                      <span>{doc.fact_checked_count} checked</span>
                    </div>
                  </button>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </aside>
  );
}
