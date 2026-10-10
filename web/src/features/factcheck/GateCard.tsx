import { AnimatePresence, motion } from "motion/react";
import { TriangleAlert } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Kbd } from "@/components/ui/kbd";
import { Switch } from "@/components/ui/switch";
import type { GateInfo } from "@/lib/types";

const LABEL: Record<string, string> = {
  meta_dialogue_or_satire: "Meta-dialogue or satire detected",
  filler: "Conversational filler detected",
};

interface Props {
  itemId: string | null;
  gate: Partial<GateInfo> | null;
  autoSkip: boolean;
  onDecide: (itemId: string, check: boolean) => void;
  onAutoSkip: (on: boolean) => void;
}

/** The pause-and-decide gate: Skip (Y), Fact-check (N), Auto-skip toggle (S). */
export function GateCard({ itemId, gate, autoSkip, onDecide, onAutoSkip }: Props) {
  const title = gate?.label ? (LABEL[gate.label] ?? `Gate: ${gate.label}`) : "Not check-worthy by the rule gate";
  const source = gate?.source === "jev" ? "jev check-worthiness" : "rule gate";
  return (
    <AnimatePresence initial={false} mode="popLayout">
      {itemId && gate && !autoSkip ? (
        <motion.section
          key={itemId}
          initial={{ opacity: 0, y: -6 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -6 }}
          transition={{ duration: 0.16, ease: "easeOut" }}
          role="alertdialog"
          aria-label="Fact-check gate"
          data-testid="gate"
          className="grid gap-2.5 rounded-xl bg-warn/[0.07] px-4 py-3.5 shadow-[inset_0_0_0_1px_color-mix(in_oklab,var(--warn)_25%,transparent)]"
        >
          <div className="flex items-center gap-2.5 font-semibold text-warn">
            <TriangleAlert className="size-4" />
            {title}
            <small className="ml-auto font-mono text-[11.5px] font-medium text-muted" data-testid="gate-probability">
              {source}
              {gate.probability !== null && gate.probability !== undefined && ` · p=${gate.probability.toFixed(2)}`}
            </small>
          </div>
          {gate.reason && <p className="text-[12.5px] text-muted">{gate.reason}</p>}
          <div className="flex flex-wrap items-center gap-2">
            <Button onClick={() => onDecide(itemId, false)}>
              Skip <Kbd>Y</Kbd>
            </Button>
            <Button variant="primary" onClick={() => onDecide(itemId, true)}>
              Fact-check <Kbd className="bg-black/15 text-primary-fg shadow-none">N</Kbd>
            </Button>
            <label className="ml-auto flex items-center gap-2 text-[12.5px] text-muted">
              <Switch checked={autoSkip} onCheckedChange={onAutoSkip} aria-label="Auto-skip meta-dialogue" />
              Auto-skip meta-dialogue <Kbd>S</Kbd>
            </label>
          </div>
        </motion.section>
      ) : null}
    </AnimatePresence>
  );
}
