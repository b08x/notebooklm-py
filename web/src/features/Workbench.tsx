import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Panel, PanelGroup, PanelResizeHandle } from "react-resizable-panels";
import { useSearch, useStats } from "@/lib/queries";
import { setRowIds } from "@/state/rows";
import { actions, useApp } from "@/state/store";
import { BrowseTable } from "./BrowseTable";
import { DetailPane } from "./DetailPane";
import { FiltersPane } from "./FiltersPane";
import { MapView } from "./MapView";
import { NewChunksPill } from "./NewChunksPill";
import { RunsView } from "./RunsView";
import { SearchResults } from "./SearchResults";
import { SelectionBar } from "./SelectionBar";
import { toggleRow } from "./selection";

/** Tracks the max clause id the results were loaded at; the pill counts newer chunks. */
function useNewChunks(): [number, () => void] {
  const filters = useApp((s) => s.filters);
  const qc = useQueryClient();
  const [baseline, setBaseline] = useState<number | null>(null);
  const stats = useStats(filters, baseline);
  useEffect(() => {
    if (baseline === null && stats.data) setBaseline(stats.data.filtered_max_clause_id);
  }, [baseline, stats.data]);
  useEffect(() => setBaseline(null), [filters]);
  const count = baseline !== null ? (stats.data?.new_since ?? 0) : 0;
  const refresh = () => {
    setBaseline(null);
    void qc.invalidateQueries({ queryKey: ["search"] });
    void qc.invalidateQueries({ queryKey: ["browse"] });
    void qc.invalidateQueries({ queryKey: ["facets"] });
  };
  return [count, refresh];
}

function SearchCenter({ pill }: { pill: React.ReactNode }) {
  const query = useApp((s) => s.submittedQuery);
  const mode = useApp((s) => s.mode);
  const filters = useApp((s) => s.filters);
  const selected = useApp((s) => s.selected);
  const cursor = useApp((s) => s.cursor);
  const detailId = useApp((s) => s.detailId);
  const hidden = useApp((s) => s.hidden);
  const q = useSearch(query, mode, filters);
  useEffect(() => {
    setRowIds((q.data?.hits ?? []).filter((h) => !hidden.includes(h.external_id)).map((h) => h.external_id));
  }, [q.data, hidden]);
  return (
    <SearchResults
      result={q.data}
      loading={q.isFetching}
      query={query}
      selected={selected}
      cursor={cursor}
      detailId={detailId}
      hidden={hidden}
      onOpen={actions.open}
      onToggle={toggleRow}
      header={pill}
    />
  );
}

export function Workbench() {
  const tab = useApp((s) => s.tab);
  const [newCount, refresh] = useNewChunks();
  const pill = <NewChunksPill count={newCount} onClick={refresh} />;
  return (
    <PanelGroup direction="horizontal" autoSaveId="ce-panes" className="min-h-0 flex-1">
      <Panel defaultSize={17} minSize={12} maxSize={30} className="min-w-0 overflow-hidden border-r border-line">
        <FiltersPane />
      </Panel>
      <PanelResizeHandle className="w-px bg-line transition-[background-color] duration-150 data-[resize-handle-state=drag]:bg-primary data-[resize-handle-state=hover]:bg-primary/60" />
      <Panel minSize={30} className="flex min-w-0 flex-col overflow-hidden">
        {tab === "search" && <SearchCenter pill={pill} />}
        {tab === "browse" && <BrowseTable header={pill} />}
        {tab === "map" && <MapView />}
        {tab === "runs" && <RunsView />}
        {(tab === "search" || tab === "browse") && <SelectionBar />}
      </Panel>
      <PanelResizeHandle className="w-px bg-line transition-[background-color] duration-150 data-[resize-handle-state=drag]:bg-primary data-[resize-handle-state=hover]:bg-primary/60" />
      <Panel defaultSize={28} minSize={20} maxSize={45} className="min-w-0 overflow-hidden border-l border-line">
        <DetailPane />
      </Panel>
    </PanelGroup>
  );
}
