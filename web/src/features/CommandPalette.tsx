import { Command } from "cmdk";
import { CloudDownload, Keyboard, MessageSquareText, Moon, Search, ShieldCheck, Trash2 } from "lucide-react";
import type * as React from "react";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { Kbd } from "@/components/ui/kbd";
import { toggleTheme } from "@/lib/theme";
import { TABS, actions, store, useApp } from "@/state/store";
import { deleteSelection } from "./SelectionBar";

export function focusSearch(): void {
  const el = document.getElementById("corpus-search") as HTMLInputElement | null;
  if (store.get().tab !== "search") actions.setTab("search");
  requestAnimationFrame(() => {
    const input = (document.getElementById("corpus-search") as HTMLInputElement | null) ?? el;
    input?.focus();
    input?.select();
  });
}

export function startFactCheckFromContext(): void {
  const s = store.get();
  if (s.selected.length) actions.startFactCheck({ external_ids: s.selected });
  else if (s.filters.notebook_ids?.length === 1) actions.startFactCheck({ notebook_id: s.filters.notebook_ids[0] });
  else actions.setTab("factcheck");
}

function Item({ onSelect, children, shortcut, value }: { onSelect: () => void; children: React.ReactNode; shortcut?: string; value: string }) {
  return (
    <Command.Item
      value={value}
      onSelect={() => {
        store.set({ paletteOpen: false });
        onSelect();
      }}
      className="flex cursor-default items-center gap-2.5 rounded-md px-2.5 py-2 text-[13px] text-fg data-[selected=true]:bg-surface-2 [&_svg]:size-4 [&_svg]:text-muted"
    >
      {children}
      {shortcut && <Kbd className="ml-auto">{shortcut}</Kbd>}
    </Command.Item>
  );
}

/** Cmd/Ctrl-K: switch tabs, focus search, delete selection, start a fact-check run, toggle theme. */
export function CommandPalette() {
  const open = useApp((s) => s.paletteOpen);
  const selected = useApp((s) => s.selected);
  return (
    <Dialog open={open} onOpenChange={(o) => store.set({ paletteOpen: o })}>
      <DialogContent className="top-[18%] translate-y-0 p-0" aria-describedby={undefined}>
        <DialogTitle className="sr-only">Command palette</DialogTitle>
        <Command label="Command palette" className="overflow-hidden rounded-xl">
          <Command.Input
            autoFocus
            placeholder="Type a command…"
            className="h-11 w-full border-b border-line bg-transparent px-3.5 text-[14px] text-fg outline-none placeholder:text-subtle"
          />
          <Command.List className="max-h-80 overflow-auto p-1.5">
            <Command.Empty className="p-4 text-center text-[12.5px] text-muted">No matching command.</Command.Empty>
            <Command.Group heading="Go to" className="[&_[cmdk-group-heading]]:px-2.5 [&_[cmdk-group-heading]]:py-1 [&_[cmdk-group-heading]]:text-[11px] [&_[cmdk-group-heading]]:text-subtle">
              {TABS.map((t, i) => (
                <Item key={t.id} value={`go ${t.label}`} onSelect={() => actions.setTab(t.id)} shortcut={String(i + 1)}>
                  <span className="grid size-4 place-items-center font-mono text-[10px] text-muted">{i + 1}</span>
                  {t.label}
                </Item>
              ))}
            </Command.Group>
            <Command.Group heading="Actions" className="[&_[cmdk-group-heading]]:px-2.5 [&_[cmdk-group-heading]]:py-1 [&_[cmdk-group-heading]]:text-[11px] [&_[cmdk-group-heading]]:text-subtle">
              <Item value="focus search" onSelect={focusSearch} shortcut="/">
                <Search /> Focus search
              </Item>
              <Item value="ask question answer" onSelect={() => store.set({ askOpen: true })}>
                <MessageSquareText /> Ask over results
              </Item>
              <Item value="start fact-check run" onSelect={startFactCheckFromContext}>
                <ShieldCheck /> Start fact-check run
              </Item>
              {selected.length > 0 && (
                <Item value="delete selection" onSelect={deleteSelection} shortcut="⌫">
                  <Trash2 /> Delete selection ({selected.length})
                </Item>
              )}
              <Item value="ingest artifact" onSelect={() => store.set({ ingestOpen: true })}>
                <CloudDownload /> Ingest artifact
              </Item>
              <Item value="toggle theme dark light" onSelect={() => toggleTheme()}>
                <Moon /> Toggle theme
              </Item>
              <Item value="keyboard shortcuts help" onSelect={() => store.set({ shortcutsOpen: true })} shortcut="?">
                <Keyboard /> Keyboard shortcuts
              </Item>
            </Command.Group>
          </Command.List>
        </Command>
      </DialogContent>
    </Dialog>
  );
}
