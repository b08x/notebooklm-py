import { AnimatePresence, motion } from "motion/react";
import { ChevronDown, Download, MessageSquareText, ShieldCheck, Trash2, X } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { Kbd } from "@/components/ui/kbd";
import { fmt } from "@/lib/utils";
import { actions, store, useApp } from "@/state/store";
import { downloadExport, pushAsNote } from "./exports";

export function deleteSelection(): void {
  const ids = store.get().selected;
  if (!ids.length) return;
  actions.requestDelete({ level: "clause", ids, hide: ids, label: `${ids.length} selected ${ids.length === 1 ? "chunk" : "chunks"}` });
}

/** Bulk actions for the multi-selection: Delete, Export, Re-fact-check, Ask. */
export function SelectionBar() {
  const selected = useApp((s) => s.selected);
  const run = (p: Promise<void>) => p.catch((e: Error) => toast.error(e.message));
  return (
    <AnimatePresence initial={false}>
      {selected.length > 0 && (
        <motion.div
          key="bulk"
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: 8 }}
          transition={{ duration: 0.16, ease: "easeOut" }}
          role="toolbar"
          aria-label="Selection actions"
          className="flex items-center gap-2 border-t border-line bg-surface px-3.5 py-2.5 text-[12.5px]"
        >
          <span className="tabular" data-testid="selection-count">
            {fmt.format(selected.length)} selected
          </span>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button>
                <Download /> Export <ChevronDown />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent>
              <DropdownMenuItem onSelect={() => run(downloadExport(selected, "markdown"))}>Download Markdown</DropdownMenuItem>
              <DropdownMenuItem onSelect={() => run(downloadExport(selected, "json"))}>Download JSON</DropdownMenuItem>
              <DropdownMenuItem onSelect={() => run(pushAsNote(selected))}>Push as note to NotebookLM</DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
          <Button onClick={() => actions.startFactCheck({ external_ids: selected })}>
            <ShieldCheck /> Re-fact-check
          </Button>
          <Button variant="destructive" onClick={deleteSelection}>
            <Trash2 /> Delete <Kbd className="ml-0.5">⌫</Kbd>
          </Button>
          <Button variant="ghost" size="icon" aria-label="Clear selection" onClick={actions.clearSelection}>
            <X />
          </Button>
          <Button variant="primary" className="ml-auto" onClick={() => store.set({ askOpen: true })}>
            <MessageSquareText /> Ask about selection
          </Button>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
