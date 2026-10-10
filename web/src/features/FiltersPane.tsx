import * as Slider from "@radix-ui/react-slider";
import { useState } from "react";
import { Checkbox } from "@/components/ui/checkbox";
import { SectionLabel } from "@/components/ui/section-label";
import { Switch } from "@/components/ui/switch";
import { useFacets, useStats } from "@/lib/queries";
import type { FacetValue, Filters } from "@/lib/types";
import { cn, fmt, shortId } from "@/lib/utils";
import { actions, useApp } from "@/state/store";

const LABELS: Record<string, string> = {
  clean: "Clean",
  base64: "Base64 / binary",
  numeric_table: "Numeric tables",
  unchecked: "Unchecked",
  passed: "Passed",
  failed: "Failed",
  other: "Not check-worthy / other",
  source: "Source",
  note: "Note",
  audio: "Audio",
  video: "Video",
  report: "Report",
  quiz: "Quiz",
  flashcards: "Flashcards",
  mind_map: "Mind map",
  data_table: "Data table",
};

type ListKey = "notebook_ids" | "document_ids" | "kinds" | "quality" | "fact_check" | "strategies" | "run_ids";

function Facet({
  title,
  values,
  field,
  filters,
  limit = 8,
  format,
}: {
  title: string;
  values: FacetValue[] | undefined;
  field: ListKey;
  filters: Filters;
  limit?: number;
  format?: (v: string) => string;
}) {
  const [expanded, setExpanded] = useState(false);
  const chosen = (filters[field] as (string | number)[] | undefined) ?? [];
  const rows = (values ?? []).filter((v) => v.value !== null);
  const shown = expanded ? rows : rows.slice(0, limit);
  if (!rows.length) return null;
  const toggle = (value: string | number) => {
    const next = chosen.includes(value) ? chosen.filter((x) => x !== value) : [...chosen, value];
    actions.setFilters({ [field]: next.length ? next : undefined } as Partial<Filters>);
  };
  return (
    <section className="mb-4" aria-label={title}>
      <SectionLabel>{title}</SectionLabel>
      {shown.map((v) => {
        const value = v.value as string | number;
        const label = format ? format(String(value)) : (LABELS[String(value)] ?? String(value));
        return (
          <label
            key={String(value)}
            className="flex cursor-default items-center gap-2 rounded-md px-1.5 py-1 text-[13px] transition-[background-color] duration-150 hover:bg-surface"
          >
            <Checkbox checked={chosen.includes(value)} onCheckedChange={() => toggle(value)} aria-label={label} />
            <span className="min-w-0 truncate" title={String(value)}>
              {label}
            </span>
            <em className="ml-auto text-[12px] text-muted not-italic tabular" data-testid={`facet-count-${field}-${value}`}>
              {fmt.format(v.count)}
            </em>
          </label>
        );
      })}
      {rows.length > limit && (
        <button
          type="button"
          onClick={() => setExpanded((x) => !x)}
          className="mt-0.5 px-1.5 text-[12px] text-muted transition-[color,scale] duration-150 hover:text-fg active:scale-[0.96]"
        >
          {expanded ? "Show fewer" : `Show all ${rows.length}`}
        </button>
      )}
    </section>
  );
}

function Stat({ value, label }: { value: number | undefined; label: string }) {
  return (
    <div className="rounded-lg bg-surface p-2 shadow-[inset_0_0_0_1px_var(--line)]">
      <b className="block text-[16px] font-semibold tabular">{value === undefined ? "—" : fmt.format(value)}</b>
      <small className="text-[11px] text-muted">{label}</small>
    </div>
  );
}

const MAX_LEN = 2000;

function LengthRange({ filters }: { filters: Filters }) {
  const lo = filters.min_len ?? 0;
  const hi = filters.max_len ?? MAX_LEN;
  const [draft, setDraft] = useState<[number, number] | null>(null);
  const [a, b] = draft ?? [lo, hi];
  return (
    <section className="mb-4" aria-label="Length">
      <SectionLabel>
        Length · {a}–{b >= MAX_LEN ? `${MAX_LEN}+` : b} chars
      </SectionLabel>
      <Slider.Root
        className="relative mx-1 mt-3 mb-1 flex h-4 touch-none items-center select-none"
        min={0}
        max={MAX_LEN}
        step={10}
        value={[a, b]}
        onValueChange={(v) => setDraft([v[0], v[1]])}
        onValueCommit={(v) => {
          setDraft(null);
          actions.setFilters({ min_len: v[0] > 0 ? v[0] : undefined, max_len: v[1] < MAX_LEN ? v[1] : undefined });
        }}
        aria-label="Chunk length range"
      >
        <Slider.Track className="relative h-1 grow rounded-[2px] bg-surface-2">
          <Slider.Range className="absolute h-full rounded-[2px] bg-primary" />
        </Slider.Track>
        <Slider.Thumb className="block size-3 rounded-full bg-fg shadow-pop" aria-label="Minimum length" />
        <Slider.Thumb className="block size-3 rounded-full bg-fg shadow-pop" aria-label="Maximum length" />
      </Slider.Root>
    </section>
  );
}

export function FiltersPane() {
  const filters = useApp((s) => s.filters);
  const stats = useStats(filters);
  const facets = useFacets(filters);
  const f = facets.data;
  const active = Object.values(filters).some((v) => (Array.isArray(v) ? v.length : v !== undefined && v !== false));
  return (
    <aside aria-label="Filters" className="h-full overflow-auto px-3 py-3.5">
      <div className="mb-4">
        <div className="mb-2 flex items-center">
          <SectionLabel className="mb-0">Corpus</SectionLabel>
          {active && (
            <button
              type="button"
              className="ml-auto text-[12px] text-muted transition-[color,scale] duration-150 hover:text-fg active:scale-[0.96]"
              onClick={() => actions.setFilters({
                notebook_ids: undefined, document_ids: undefined, run_ids: undefined, strategies: undefined,
                kinds: undefined, fact_check: undefined, quality: undefined, min_len: undefined, max_len: undefined,
                has_near_duplicate: undefined,
              })}
            >
              Clear filters
            </button>
          )}
        </div>
        <div className="grid grid-cols-2 gap-1.5" data-testid="corpus-stats">
          <Stat value={stats.data?.clauses} label="clauses" />
          <Stat value={stats.data?.parents} label="parents" />
          <Stat value={stats.data?.documents} label="documents" />
          <Stat value={stats.data?.runs} label="runs" />
        </div>
      </div>
      <Facet title="Notebook" values={f?.notebook} field="notebook_ids" filters={filters} format={(v) => shortId(v, 18)} />
      <Facet title="Kind" values={f?.kind} field="kinds" filters={filters} />
      <Facet title="Quality" values={f?.quality} field="quality" filters={filters} />
      <section className="mb-4" aria-label="Near-duplicates">
        <label className="flex items-center gap-2 px-1.5 text-[13px]">
          <Switch
            checked={!!filters.has_near_duplicate}
            onCheckedChange={(on) => actions.setFilters({ has_near_duplicate: on || undefined })}
            aria-label="Only chunks with a near-duplicate"
          />
          Has a near-duplicate
        </label>
      </section>
      <Facet title="Fact-check" values={f?.fact_check} field="fact_check" filters={filters} />
      <LengthRange filters={filters} />
      <Facet title="Strategy" values={f?.strategy} field="strategies" filters={filters} />
      <Facet title="Document" values={f?.document} field="document_ids" filters={filters} limit={6} format={(v) => shortId(v, 22)} />
      <Facet title="Run" values={f?.run} field="run_ids" filters={filters} limit={6} format={(v) => `run #${v}`} />
      {facets.isError && <p className={cn("text-[12px] text-bad")}>Facets failed to load.</p>}
    </aside>
  );
}
