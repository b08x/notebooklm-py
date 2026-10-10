import { Badge } from "@/components/ui/badge";
import type { ChunkRow } from "@/lib/types";
import { shortId } from "@/lib/utils";

const QUALITY_LABEL: Record<string, string> = { base64: "base64", numeric_table: "numeric table" };
const FC_TONE = { passed: "ok", failed: "bad", other: "neutral", unchecked: "neutral" } as const;

export function RowMeta({ row }: { row: ChunkRow }) {
  return (
    <div className="flex flex-wrap gap-2 font-mono text-[11.5px] text-muted">
      <span>#{row.id}</span>
      <span title={row.document_id}>doc {shortId(row.title ?? row.document_id, 14)}</span>
      {row.sentence_index !== null && <span>line {row.sentence_index}</span>}
      {row.kind !== "source" && <Badge tone="info">{row.kind.replace("_", " ")}</Badge>}
      {row.strategy && <Badge>{row.strategy}</Badge>}
      {row.quality !== "clean" && <Badge tone="bad">{QUALITY_LABEL[row.quality]}</Badge>}
      {row.fact_check !== "unchecked" && (
        <Badge tone={FC_TONE[row.fact_check]}>{row.fact_check === "other" ? "checked" : row.fact_check}</Badge>
      )}
      {!row.is_active && <Badge tone="warn">inactive run</Badge>}
    </div>
  );
}
