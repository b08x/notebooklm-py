import { type ColumnDef, flexRender, getCoreRowModel, useReactTable } from "@tanstack/react-table";
import { useVirtualizer } from "@tanstack/react-virtual";
import { Columns3 } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useBrowse } from "@/lib/queries";
import type { ChunkRow } from "@/lib/types";
import { cn, fmt, shortId } from "@/lib/utils";
import { setRowIds } from "@/state/rows";
import { actions, useApp } from "@/state/store";
import { toggleRow } from "./selection";

const ROW_H = 36;
const SIZING_KEY = "ce-browse-colsizing";
const VISIBILITY_KEY = "ce-browse-colvis";

function loadJson(key: string): Record<string, unknown> | undefined {
  try {
    const raw = localStorage.getItem(key);
    return raw ? (JSON.parse(raw) as Record<string, unknown>) : undefined;
  } catch {
    return undefined;
  }
}

function saveJson(key: string, value: Record<string, unknown>): void {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    // private mode or full storage: persistence is best-effort
  }
}

const COLUMN_LABELS: Record<string, string> = {
  select: "Selector",
  id: "#",
  text: "Chunk",
  doc: "Document",
  kind: "Kind",
  len: "Len",
  quality: "Quality",
  fc: "Fact-check",
};

export function BrowseTable({ header }: { header?: React.ReactNode }) {
  const filters = useApp((s) => s.filters);
  const selected = useApp((s) => s.selected);
  const detailId = useApp((s) => s.detailId);
  const cursor = useApp((s) => s.cursor);
  const hidden = useApp((s) => s.hidden);
  const q = useBrowse(filters);
  const rows = useMemo(
    () => (q.data?.pages.flatMap((p) => p.items) ?? []).filter((r) => !hidden.includes(r.external_id)),
    [q.data, hidden],
  );
  const total = q.data?.pages[0]?.total ?? 0;

  useEffect(() => setRowIds(rows.map((r) => r.external_id)), [rows]);

  const columns = useMemo<ColumnDef<ChunkRow>[]>(
    () => [
      {
        id: "select",
        size: 32,
        enableHiding: false,
        enableResizing: false,
        header: () => null,
        cell: ({ row }) => (
          <span onClick={(e) => e.stopPropagation()}>
            <Checkbox
              aria-label="Select chunk"
              checked={selected.includes(row.original.external_id)}
              onClick={(e) => {
                e.preventDefault();
                toggleRow(row.original.external_id, e.shiftKey);
              }}
            />
          </span>
        ),
      },
      { id: "id", header: "#", size: 56, cell: ({ row }) => <span className="font-mono text-[11.5px] text-muted tabular">{row.original.id}</span> },
      {
        id: "text",
        header: "Chunk",
        size: 520,
        enableResizing: false,
        cell: ({ row }) => (
          <span className={cn("block truncate", row.original.quality !== "clean" && "font-mono text-[12px] text-muted")}>{row.original.text}</span>
        ),
      },
      {
        id: "doc",
        header: "Document",
        size: 112,
        cell: ({ row }) => {
          const doc = row.original.title ?? `${shortId(row.original.document_id, 8)} untitled`;
          return (
            <span className="truncate font-mono text-[11.5px] text-muted" title={doc}>
              {doc}
            </span>
          );
        },
      },
      { id: "kind", header: "Kind", size: 76, cell: ({ row }) => <Badge tone={row.original.kind === "source" ? "neutral" : "info"}>{row.original.kind.replace("_", " ")}</Badge> },
      { id: "len", header: "Len", size: 56, cell: ({ row }) => <span className="font-mono text-[11.5px] text-muted tabular">{row.original.length}</span> },
      {
        id: "quality",
        header: "Quality",
        size: 76,
        cell: ({ row }) => (row.original.quality === "clean" ? <span className="text-subtle">clean</span> : <Badge tone="bad">{row.original.quality === "base64" ? "base64" : "numeric"}</Badge>),
      },
      {
        id: "fc",
        header: "Fact-check",
        size: 84,
        cell: ({ row }) => {
          const v = row.original.fact_check;
          return v === "unchecked" ? <span className="text-subtle">—</span> : <Badge tone={v === "passed" ? "ok" : v === "failed" ? "bad" : "neutral"}>{v}</Badge>;
        },
      },
    ],
    [selected],
  );

  const [columnSizing, setColumnSizing] = useState<Record<string, number>>(
    () => (loadJson(SIZING_KEY) as Record<string, number>) ?? {},
  );
  const [columnVisibility, setColumnVisibility] = useState<Record<string, boolean>>(
    () => (loadJson(VISIBILITY_KEY) as Record<string, boolean>) ?? {},
  );

  const table = useReactTable({
    data: rows,
    columns,
    getCoreRowModel: getCoreRowModel(),
    getRowId: (r) => r.external_id,
    columnResizeMode: "onChange",
    onColumnSizingChange: setColumnSizing,
    onColumnVisibilityChange: setColumnVisibility,
    state: { columnSizing, columnVisibility },
  });
  const parentRef = useRef<HTMLDivElement>(null);
  const virtualizer = useVirtualizer({
    count: rows.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => ROW_H,
    overscan: 12,
  });
  const items = virtualizer.getVirtualItems();
  const last = items[items.length - 1];

  useEffect(() => {
    if (last && last.index >= rows.length - 40 && q.hasNextPage && !q.isFetchingNextPage) void q.fetchNextPage();
  }, [last, rows.length, q]);

  useEffect(() => {
    if (!cursor) return;
    const index = rows.findIndex((r) => r.external_id === cursor);
    if (index >= 0) virtualizer.scrollToIndex(index, { align: "auto" });
  }, [cursor, rows, virtualizer]);

  const tableRows = table.getRowModel().rows;
  const headers = table.getHeaderGroups()[0].headers;
  const template = headers.map((h) => (h.column.id === "text" ? "minmax(0,1fr)" : `${h.getSize()}px`)).join(" ");

  useEffect(() => {
    saveJson(SIZING_KEY, columnSizing);
  }, [columnSizing]);
  useEffect(() => {
    saveJson(VISIBILITY_KEY, columnVisibility);
  }, [columnVisibility]);

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex items-center gap-2.5 border-b border-line px-3.5 py-2.5 text-[12px] text-muted">
        <span className="tabular" data-testid="browse-total">
          {q.isLoading ? "Loading…" : `${fmt.format(total)} chunks`}
        </span>
        <span>ordered by id · {fmt.format(rows.length)} loaded</span>
        {header}
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" size="sm" className="ml-auto" aria-label="Columns" data-testid="columns-trigger">
              <Columns3 /> Columns
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            {table.getAllLeafColumns().filter((c) => c.getCanHide()).map((c) => (
              <DropdownMenuCheckboxItem
                key={c.id}
                checked={c.getIsVisible()}
                onCheckedChange={(v) => c.toggleVisibility(!!v)}
                onSelect={(e) => e.preventDefault()}
                data-testid={`column-toggle-${c.id}`}
              >
                {COLUMN_LABELS[c.id] ?? c.id}
              </DropdownMenuCheckboxItem>
            ))}
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
      <div role="table" aria-label="All chunks" aria-rowcount={total} className="flex min-h-0 flex-1 flex-col text-[13px]">
        <div role="row" className="grid border-b border-line px-3.5 py-1.5 text-[11px] font-semibold tracking-[0.06em] text-subtle uppercase" style={{ gridTemplateColumns: template, columnGap: 12 }}>
          {headers.map((h) => (
            <span role="columnheader" key={h.id} className="relative">
              {flexRender(h.column.columnDef.header, h.getContext())}
              {h.column.getCanResize() && (
                <span
                  role="separator"
                  aria-orientation="vertical"
                  aria-label={`Resize ${COLUMN_LABELS[h.column.id] ?? h.column.id}`}
                  data-testid={`resize-${h.column.id}`}
                  onMouseDown={h.getResizeHandler()}
                  onDoubleClick={() => h.column.resetSize()}
                  className={cn(
                    "absolute -right-1.5 top-0 h-full w-2 cursor-col-resize touch-none rounded transition-[background-color] duration-150 hover:bg-primary/60",
                    h.column.getIsResizing() && "bg-primary/60",
                  )}
                />
              )}
            </span>
          ))}
        </div>
        <div ref={parentRef} className="min-h-0 flex-1 overflow-auto" data-testid="browse-scroll">
          <div style={{ height: virtualizer.getTotalSize(), position: "relative" }}>
            {items.map((v) => {
              const row = tableRows[v.index];
              if (!row) return null;
              const id = row.original.external_id;
              return (
                <div
                  key={row.id}
                  role="row"
                  data-row-id={id}
                  onClick={() => actions.open(id)}
                  className={cn(
                    "absolute inset-x-0 grid items-center border-b border-line/60 px-3.5 transition-[background-color] duration-150 hover:bg-surface/60",
                    detailId === id && "bg-selection shadow-[inset_2px_0_0_var(--primary)]",
                    cursor === id && detailId !== id && "bg-surface/80",
                  )}
                  style={{ top: v.start, height: ROW_H, gridTemplateColumns: template, columnGap: 12 }}
                >
                  {row.getVisibleCells().map((cell) => (
                    <span role="cell" key={cell.id} className="min-w-0">
                      {flexRender(cell.column.columnDef.cell, cell.getContext())}
                    </span>
                  ))}
                </div>
              );
            })}
          </div>
          {!q.isLoading && rows.length === 0 && <p className="p-10 text-center text-[13px] text-muted">No chunks match these filters.</p>}
        </div>
      </div>
    </div>
  );
}
