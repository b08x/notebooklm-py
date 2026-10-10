import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { Kbd } from "@/components/ui/kbd";
import { store, useApp } from "@/state/store";

const GROUPS: [string, [string, string][]][] = [
  [
    "Workbench",
    [
      ["/", "Focus search"],
      ["j / k", "Move down / up"],
      ["x", "Select row (shift extends)"],
      ["Enter", "Open chunk"],
      ["⌫", "Delete selection or open chunk"],
      ["Esc", "Clear selection / close"],
      ["1 – 5", "Switch tab"],
      ["⌘K", "Command palette"],
      ["?", "This sheet"],
    ],
  ],
  [
    "Fact-check",
    [
      ["Y", "Skip flagged chunk"],
      ["N", "Fact-check it anyway"],
      ["S", "Toggle auto-skip"],
      ["j / k", "Move in queue"],
    ],
  ],
];

export function ShortcutSheet() {
  const open = useApp((s) => s.shortcutsOpen);
  return (
    <Dialog open={open} onOpenChange={(o) => store.set({ shortcutsOpen: o })}>
      <DialogContent className="w-[min(520px,calc(100vw-32px))]" aria-describedby="keys-desc">
        <DialogTitle>Keyboard shortcuts</DialogTitle>
        <DialogDescription id="keys-desc" className="mb-3">
          Everything in the explorer works from the keyboard.
        </DialogDescription>
        <div className="grid grid-cols-2 gap-5">
          {GROUPS.map(([title, rows]) => (
            <dl key={title} className="grid content-start gap-1.5 text-[12.5px]">
              <dt className="mb-1 text-[11px] font-semibold tracking-[0.06em] text-subtle uppercase">{title}</dt>
              {rows.map(([k, label]) => (
                <dd key={k} className="m-0 flex items-center justify-between gap-3">
                  <span className="text-muted">{label}</span>
                  <Kbd>{k}</Kbd>
                </dd>
              ))}
            </dl>
          ))}
        </div>
      </DialogContent>
    </Dialog>
  );
}
