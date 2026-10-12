import { ChevronRight } from "lucide-react";
import { useDetail, useFacets, useNotebookTitles } from "@/lib/queries";
import { clauseNumber, documentLabel, notebookLabel } from "@/lib/utils";
import { store, useApp } from "@/state/store";
import { TABS } from "@/state/url";

/**
 * Tab › Notebook › Document › Chunk, shown under the header when a segment is
 * known (an open chunk or a single-valued notebook/document filter).
 */
export function Breadcrumbs() {
  const tab = useApp((s) => s.tab);
  const detailId = useApp((s) => s.detailId);
  const filters = useApp((s) => s.filters);
  const titles = useNotebookTitles();
  const facets = useFacets(filters).data;
  const detail = useDetail(detailId).data;

  const single = (ids: string[] | undefined) => (ids?.length === 1 ? ids[0] : null);
  const notebook = detail?.notebook_id ?? single(filters.notebook_ids);
  const document = detail?.document_id ?? single(filters.document_ids);
  const externalId = detail?.external_id ?? (detailId ? clauseNumber(detailId) : null);
  if (!notebook && !document && !detailId) return null;

  return (
    <nav aria-label="Breadcrumb" data-testid="breadcrumb" className="flex h-7 shrink-0 items-center gap-1 border-b border-line px-3 text-[12px] text-muted">
      <button
        type="button"
        data-testid="crumb-tab"
        onClick={() =>
          store.set((s) => ({
            detailId: null,
            filters: { ...s.filters, notebook_ids: undefined, document_ids: undefined },
          }))
        }
        className="rounded px-1 transition-[color,background-color] duration-150 hover:bg-surface-2 hover:text-fg"
      >
        {TABS.find((t) => t.id === tab)?.label}
      </button>
      {notebook && (
        <>
          <ChevronRight className="size-3 text-subtle" aria-hidden />
          <button
            type="button"
            data-testid="crumb-notebook"
            onClick={() => store.set({ detailId: null, filters: { notebook_ids: [notebook] } })}
            className="max-w-[240px] truncate rounded px-1 transition-[color,background-color] duration-150 hover:bg-surface-2 hover:text-fg"
            title={notebook}
          >
            {notebookLabel(notebook, titles)}
          </button>
        </>
      )}
      {document && (
        <>
          <ChevronRight className="size-3 text-subtle" aria-hidden />
          <button
            type="button"
            data-testid="crumb-document"
            onClick={() =>
              store.set((s) => ({ detailId: null, filters: { ...s.filters, document_ids: [document] } }))
            }
            className="max-w-[240px] truncate rounded px-1 transition-[color,background-color] duration-150 hover:bg-surface-2 hover:text-fg"
            title={document}
          >
            {documentLabel(document, detail?.title ? { [document]: detail.title } : facets?.labels?.document)}
          </button>
        </>
      )}
      {detailId && (
        <>
          <ChevronRight className="size-3 text-subtle" aria-hidden />
          <span data-testid="crumb-chunk" className="truncate px-1 text-fg">
            {externalId ? clauseNumber(externalId) : clauseNumber(detailId)}
          </span>
        </>
      )}
    </nav>
  );
}
