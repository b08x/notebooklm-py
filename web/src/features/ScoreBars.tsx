import { cn } from "@/lib/utils";

interface Props {
  kwRank: number | null;
  vecRank: number | null;
  score: number;
  maxScore: number;
  depth: number;
}

function Bar({ label, pct, value, color }: { label: string; pct: number; value: string; color: string }) {
  return (
    <div className="grid grid-cols-[22px_1fr_38px] items-center gap-1.5" aria-label={`${label} ${value}`}>
      <span>{label}</span>
      <span className="relative h-1 overflow-hidden rounded-[2px] bg-surface-2">
        <i className="absolute inset-y-0 left-0 rounded-[2px]" style={{ width: `${Math.round(pct * 100)}%`, background: color }} />
      </span>
      <span className="text-right tabular">{value}</span>
    </div>
  );
}

/** Keyword rank, vector rank and fused RRF score for one hit. */
export function ScoreBars({ kwRank, vecRank, score, maxScore, depth }: Props) {
  const rankPct = (rank: number | null) => (rank ? 1 - (rank - 1) / Math.max(depth, 1) : 0);
  return (
    <div className={cn("grid gap-1 font-mono text-[11px] text-muted")} data-testid="score-bars">
      <Bar label="kw" pct={rankPct(kwRank)} value={kwRank ? `#${kwRank}` : "—"} color="var(--primary)" />
      <Bar label="vec" pct={rankPct(vecRank)} value={vecRank ? `#${vecRank}` : "—"} color="var(--secondary)" />
      <Bar label="rrf" pct={maxScore ? score / maxScore : 0} value={score.toFixed(4).replace(/^0/, "")} color="var(--fg)" />
    </div>
  );
}
