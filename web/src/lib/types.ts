export type Mode = "keyword" | "vector" | "hybrid";
export type DeleteLevel = "clause" | "parent" | "document" | "run";

export interface Filters {
  notebook_ids?: string[];
  document_ids?: string[];
  run_ids?: number[];
  strategies?: string[];
  kinds?: string[];
  fact_check?: string[];
  quality?: string[];
  min_len?: number;
  max_len?: number;
  has_near_duplicate?: boolean;
  text?: string;
}

export interface ChunkRow {
  id: number;
  external_id: string;
  text: string;
  document_id: string;
  run_id: number | null;
  parent_id: number | null;
  sentence_index: number | null;
  notebook_id: string | null;
  strategy: string | null;
  kind: string;
  title: string | null;
  is_active: boolean;
  length: number;
  quality: "clean" | "base64" | "numeric_table";
  fact_check: "unchecked" | "passed" | "failed" | "other";
  has_sfl: boolean;
}

export interface SearchHit extends ChunkRow {
  kw_rank: number | null;
  vec_rank: number | null;
  score: number;
  distance: number | null;
}

export interface SearchResult {
  query: string;
  mode: Mode;
  hits: SearchHit[];
  vector_leg_ok: boolean;
  keyword_count: number;
  vector_count: number;
  elapsed_ms: number;
}

export interface BrowsePage {
  items: ChunkRow[];
  next_cursor: number | null;
  total: number | null;
}

export interface FacetValue {
  value: string | number | null;
  count: number;
}
export type Facets = Record<
  "notebook" | "document" | "run" | "strategy" | "kind" | "fact_check" | "quality" | "length",
  FacetValue[]
> & { labels?: { document: Record<string, string> } };

export interface Stats {
  clauses: number;
  parents: number;
  documents: number;
  runs: number;
  all_runs: number;
  embeddings: number;
  fact_checks: number;
  max_clause_id: number;
  filtered_max_clause_id: number;
  new_since?: number;
}

export interface SflFormatted {
  ideational: { participants: string[]; processes: string[]; circumstances: string[] };
  interpersonal: { tenor: string[]; mood: string[]; modality: string[] };
}

export interface ContextLine {
  external_id: string;
  sentence_index: number;
  text: string;
}

export interface FactCheckRecord {
  verdict: string;
  confidence: number | null;
  probabilities: Record<string, number> | null;
  sift_steps: Record<string, Record<string, unknown>> | null;
  citations: { url: string; title: string; quote: string }[] | null;
  trace_id: string | null;
  model: string | null;
  created_at: string | null;
}

export interface ChunkDetail extends ChunkRow {
  parent: {
    id: number;
    index: number;
    text: string;
    char_start: number;
    char_end: number;
    child_start: number | null;
    child_end: number | null;
    n_children: number;
  } | null;
  n_parents: number | null;
  context: { before: ContextLine[]; after: ContextLine[] };
  entities: { text: string; label: string }[];
  sfl: SflFormatted | null;
  sfl_raw: unknown;
  tokens: unknown;
  groups: unknown;
  topic: string | null;
  latest_fact_check: FactCheckRecord | null;
  run: {
    id: number;
    strategy: string;
    chunker_version: string;
    is_active: boolean;
    trace_id: string | null;
    source_hash: string;
    params: Record<string, unknown>;
    created_at: string | null;
  } | null;
  created_at: string | null;
}

export interface Neighbor extends Omit<ChunkRow, "fact_check"> {
  distance: number;
  near_duplicate: boolean;
}

export interface RunRow {
  id: number;
  document_id: string;
  notebook_id: string | null;
  strategy: string;
  kind: string;
  title: string | null;
  n_parents: number;
  n_children: number;
  mean_len: number;
  p95_len: number;
  entity_vetoes: number;
  is_active: boolean;
  created_at: string | null;
}

export interface JobSnapshot {
  id: string;
  kind: string;
  label: string;
  status: "queued" | "running" | "done" | "failed" | "cancelled";
  message: string;
  done: number;
  total: number;
  result: Record<string, unknown> | null;
  error: string | null;
  document_ids: string[];
  trace_url: string | null;
  created_at: number;
  started_at: number | null;
  finished_at: number | null;
  last_seq: number;
}

export interface MapResponse {
  points: MapPoint[];
  color_by: "topic" | "document";
  method: "pca" | "umap";
}

export interface Health {
  postgres: { ok: boolean; latency_ms?: number; error?: string };
  embedder: { ok: boolean; url?: string; model?: string; error?: string };
  jobs: JobSnapshot[];
  factcheck_runs: FactCheckRunSummary[];
}

export interface DeletePreview {
  level: DeleteLevel;
  ids: string[];
  counts: { clauses: number; embeddings: number; fact_checks: number; parents: number; runs: number };
}

export interface MapPoint {
  x: number;
  y: number;
  external_id: string;
  document_id: string;
  preview: string;
  topic: string | null;
}

export interface NotebookRow {
  id: string;
  title: string | null;
  chunks: number;
  documents: number;
}

export interface ArtifactRow {
  id: string;
  title: string;
  kind: string;
  media: string;
  ingestible: boolean;
  reason: string | null;
  ingested: boolean | null;
}

export interface Provider {
  id: string;
  label: string;
  env_var: string;
  key_present: boolean;
}

export interface AnswerResult {
  mode: string;
  answer: string;
  labels: Record<string, string>;
  citations: Record<string, string>;
  hits: SearchHit[];
  notebook_id?: string;
  per_notebook?: { notebook_id: string; answer: string }[];
  experimental?: boolean;
}

export type ItemStatus =
  | "pending"
  | "active"
  | "waiting"
  | "verified"
  | "refuted"
  | "unverifiable"
  | "skipped"
  | "no_framework"
  | "error";

export interface GateInfo {
  flagged: boolean;
  reason: string;
  source: "rule" | "jev";
  label: string | null;
  probability: number | null;
  probabilities: Record<string, number> | null;
}

export interface RunItem {
  item_id: string;
  index: number;
  external_id: string;
  text: string;
  status: ItemStatus;
  reason: string | null;
  verdict: string | null;
  confidence: number | null;
  probability: number | null;
  gate: GateInfo | null;
  sift: Record<string, string>;
  sift_steps: Record<string, Record<string, unknown>> | null;
  citations: { url: string; title: string; quote: string }[] | null;
  rationale: string | null;
  trace_url: string | null;
  context: { before: ContextLine[]; after: ContextLine[] };
  sfl: SflFormatted | null;
}

export interface FactCheckRunSummary {
  id: string;
  label: string;
  status: "created" | "running" | "paused" | "finished" | "cancelled" | "failed";
  error: string | null;
  gate_source: "rule" | "jev";
  gate_mode: "interactive" | "auto";
  auto_skip: boolean;
  total: number;
  done: number;
  counts: Record<ItemStatus, number>;
  elapsed_s: number;
  last_seq: number;
  waiting: ({ item_id: string; text?: string } & Partial<GateInfo>)[];
}

export interface FactCheckRunSnapshot extends FactCheckRunSummary {
  items: RunItem[];
}

export interface RunEvent {
  seq: number;
  type: string;
  [key: string]: unknown;
}

export interface DocumentItem {
  id: string;
  document_id?: string;
  title: string;
  notebook_id?: string | null;
  collection_id: string | null;
  collection_title: string | null;
  file_type: string;
  clause_count: number;
  tagged_count: number;
  fact_checked_count: number;
  created_at?: string | null;
}

export interface DocumentsResponse {
  items?: DocumentItem[];
  documents?: DocumentItem[];
  total?: number;
}

export interface DocumentClauseItem {
  id: string;
  external_id: string;
  sentence_index: number | null;
  parent_id: number | null;
  text: string;
  length: number;
  quality: string;
  fact_check: string;
  has_sfl: boolean;
  sfl_status: string | null;
  sfl_data: SflFormatted | null;
  latest_fact_check: {
    status?: string;
    verdict?: string;
    confidence?: number;
    reason?: string;
    citations?: { url: string; title: string; quote: string }[];
    [key: string]: unknown;
  } | null;
  created_at: string | null;
}

export interface ChunkWithClauses {
  id: number;
  index: number;
  text: string;
  char_start: number;
  char_end: number;
  clause_count: number;
  tagged_count: number;
  fact_checked_count: number;
  clauses: DocumentClauseItem[];
}

export interface DocumentClausesResponse {
  document_id: string;
  title?: string;
  notebook_id?: string | null;
  collection_id?: string | null;
  collection_title?: string | null;
  chunks?: ChunkWithClauses[];
  clauses: DocumentClauseItem[];
  total: number;
}

