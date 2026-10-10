import { keepPreviousData, useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { get, post } from "./api";
import type {
  ArtifactRow,
  BrowsePage,
  ChunkDetail,
  Facets,
  FactCheckRunSnapshot,
  FactCheckRunSummary,
  Filters,
  Health,
  JobSnapshot,
  MapPoint,
  Mode,
  Neighbor,
  NotebookRow,
  Provider,
  RunRow,
  SearchResult,
  Stats,
} from "./types";

export const POLL_MS = 5000;

export function filterParams(filters: Filters): Record<string, unknown> {
  return { ...filters };
}

export const keys = {
  stats: (f: Filters) => ["stats", f] as const,
  facets: (f: Filters) => ["facets", f] as const,
  browse: (f: Filters) => ["browse", f] as const,
  search: (q: string, mode: Mode, f: Filters) => ["search", q, mode, f] as const,
  detail: (id: string) => ["chunk", id] as const,
  neighbors: (id: string) => ["neighbors", id] as const,
};

export function useHealth(enabled = true) {
  return useQuery({
    queryKey: ["health"],
    queryFn: () => get<Health>("/v1/corpus/health"),
    refetchInterval: POLL_MS,
    retry: false,
    enabled,
  });
}

export function useStats(filters: Filters, since?: number | null) {
  return useQuery({
    queryKey: [...keys.stats(filters), since ?? null],
    queryFn: () => get<Stats>("/v1/corpus/stats", { ...filterParams(filters), since: since ?? undefined }),
    refetchInterval: POLL_MS,
    placeholderData: keepPreviousData,
  });
}

export function useFacets(filters: Filters) {
  return useQuery({
    queryKey: keys.facets(filters),
    queryFn: () => get<Facets>("/v1/corpus/facets", filterParams(filters)),
    placeholderData: keepPreviousData,
  });
}

export function useSearch(query: string, mode: Mode, filters: Filters) {
  return useQuery({
    queryKey: keys.search(query, mode, filters),
    queryFn: () => post<SearchResult>("/v1/corpus/search", { query, mode, filters, top_k: 50 }),
    enabled: query.trim().length > 0,
    placeholderData: keepPreviousData,
  });
}

export const PAGE_SIZE = 200;

export function useBrowse(filters: Filters) {
  return useInfiniteQuery({
    queryKey: keys.browse(filters),
    queryFn: ({ pageParam }) =>
      get<BrowsePage>("/v1/corpus/chunks", { ...filterParams(filters), cursor: pageParam ?? undefined, limit: PAGE_SIZE }),
    initialPageParam: null as number | null,
    getNextPageParam: (last) => last.next_cursor,
  });
}

export function useDetail(id: string | null) {
  return useQuery({
    queryKey: keys.detail(id ?? ""),
    queryFn: () => get<ChunkDetail>(`/v1/corpus/chunks/${encodeURIComponent(id ?? "")}`),
    enabled: !!id,
  });
}

export function useNeighbors(id: string | null, enabled = true) {
  return useQuery({
    queryKey: keys.neighbors(id ?? ""),
    queryFn: () =>
      get<{ items: Neighbor[]; near_dup_threshold: number }>(
        `/v1/corpus/chunks/${encodeURIComponent(id ?? "")}/neighbors`,
        { k: 10 },
      ),
    enabled: !!id && enabled,
  });
}

export function useRuns() {
  return useQuery({
    queryKey: ["runs"],
    queryFn: () => get<{ items: RunRow[] }>("/v1/corpus/runs"),
    refetchInterval: POLL_MS,
  });
}

export function useMap(filters: Filters) {
  return useQuery({
    queryKey: ["map", filters],
    queryFn: () => get<{ points: MapPoint[]; color_by: "topic" | "document" }>("/v1/corpus/map", filterParams(filters)),
    staleTime: 60_000,
  });
}

export function useNotebooks() {
  return useQuery({
    queryKey: ["notebooks"],
    queryFn: () => get<{ items: NotebookRow[] }>("/v1/corpus/notebooks"),
    staleTime: 30_000,
  });
}

export function useJobs() {
  return useQuery({
    queryKey: ["jobs"],
    queryFn: () => get<{ items: JobSnapshot[] }>("/v1/corpus/jobs"),
    refetchInterval: 2000,
  });
}

export function useArtifacts(notebookId: string | null) {
  return useQuery({
    queryKey: ["artifacts", notebookId],
    queryFn: () => get<{ items: ArtifactRow[] }>("/v1/corpus/artifacts", { notebook_id: notebookId }),
    enabled: !!notebookId,
    retry: false,
  });
}

export function useProviders() {
  return useQuery({
    queryKey: ["providers"],
    queryFn: () =>
      get<{ providers: Provider[]; defaults: { provider: string; diarize: boolean; language: string } }>(
        "/v1/corpus/transcription/providers",
      ),
    staleTime: 60_000,
  });
}

export function useFactCheckRuns() {
  return useQuery({
    queryKey: ["factcheck-runs"],
    queryFn: () => get<{ items: FactCheckRunSummary[] }>("/v1/corpus/factcheck/runs"),
    refetchInterval: POLL_MS,
  });
}

export function useFactCheckRun(id: string | null) {
  return useQuery({
    queryKey: ["factcheck-run", id],
    queryFn: () => get<FactCheckRunSnapshot>(`/v1/corpus/factcheck/runs/${id}`),
    enabled: !!id,
  });
}
