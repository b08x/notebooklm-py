import { AnimatePresence, motion } from "motion/react";
import { MessageSquareText, Moon, Search, Sun } from "lucide-react";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Kbd } from "@/components/ui/kbd";
import { Tooltip } from "@/components/ui/tooltip";
import { currentTheme, toggleTheme } from "@/lib/theme";
import type { Mode } from "@/lib/types";
import { cn } from "@/lib/utils";
import { TABS, actions, store, useApp } from "@/state/store";

const MODES: { id: Mode; label: string }[] = [
  { id: "keyword", label: "Keyword" },
  { id: "vector", label: "Vector" },
  { id: "hybrid", label: "Hybrid · RRF" },
];

function ThemeToggle() {
  const [theme, setTheme] = useState(currentTheme);
  return (
    <Tooltip content="Toggle theme">
      <Button variant="ghost" size="icon" aria-label="Toggle theme" onClick={() => setTheme(toggleTheme())}>
        <AnimatePresence initial={false} mode="popLayout">
          <motion.span
            key={theme}
            initial={{ scale: 0.25, opacity: 0, filter: "blur(4px)" }}
            animate={{ scale: 1, opacity: 1, filter: "blur(0px)" }}
            exit={{ scale: 0.25, opacity: 0, filter: "blur(4px)" }}
            transition={{ type: "spring", duration: 0.3, bounce: 0 }}
            className="grid place-items-center"
          >
            {theme === "dark" ? <Moon /> : <Sun />}
          </motion.span>
        </AnimatePresence>
      </Button>
    </Tooltip>
  );
}

export function Header() {
  const tab = useApp((s) => s.tab);
  const query = useApp((s) => s.query);
  const mode = useApp((s) => s.mode);

  useEffect(() => {
    const t = setTimeout(() => {
      if (store.get().submittedQuery !== query) store.set({ submittedQuery: query.trim() });
    }, 350);
    return () => clearTimeout(t);
  }, [query]);

  return (
    <header className="flex h-12 items-center gap-3 border-b border-line px-3">
      <div className="size-[22px] shrink-0 rounded-md bg-gradient-to-br from-[#a78bfa] to-[#7dd3fc]" aria-hidden />
      <nav className="flex gap-0.5" aria-label="Views">
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            aria-current={tab === t.id ? "page" : undefined}
            onClick={() => actions.setTab(t.id)}
            className={cn(
              "rounded-md px-2.5 py-1 text-[13px] text-muted transition-[color,background-color,scale] duration-150 hover:text-fg active:scale-[0.96]",
              tab === t.id && "bg-surface-2 text-fg",
            )}
          >
            {t.label}
          </button>
        ))}
      </nav>
      {tab === "search" && (
        <>
          <form
            role="search"
            className="ml-3 flex h-8 max-w-[560px] flex-1 items-center gap-2 rounded-lg bg-surface px-2.5 shadow-[inset_0_0_0_1px_var(--line)] transition-[box-shadow] duration-150 focus-within:shadow-[inset_0_0_0_1px_var(--primary)]"
            onSubmit={(e) => {
              e.preventDefault();
              store.set({ submittedQuery: store.get().query.trim() });
            }}
          >
            <Search className="size-3.5 text-muted" />
            <input
              id="corpus-search"
              aria-label="Search the corpus"
              placeholder="Search chunks…"
              value={query}
              onChange={(e) => store.set({ query: e.target.value })}
              onKeyDown={(e) => {
                if (e.key === "Escape") (e.target as HTMLInputElement).blur();
              }}
              className="min-w-0 flex-1 bg-transparent text-[13px] text-fg outline-none placeholder:text-subtle"
            />
            <Kbd>/</Kbd>
          </form>
          <div role="radiogroup" aria-label="Search mode" className="flex rounded-lg bg-surface p-0.5 text-[12px] shadow-[inset_0_0_0_1px_var(--line)]">
            {MODES.map((m) => (
              <button
                key={m.id}
                type="button"
                role="radio"
                aria-checked={mode === m.id}
                onClick={() => store.set({ mode: m.id })}
                className={cn(
                  "rounded-md px-2.5 py-1 text-muted transition-[color,background-color,scale] duration-150 active:scale-[0.96]",
                  mode === m.id && "bg-surface-2 text-fg shadow-[0_1px_2px_#0006]",
                )}
              >
                {m.label}
              </button>
            ))}
          </div>
        </>
      )}
      <div className="ml-auto flex items-center gap-1.5">
        {(tab === "search" || tab === "browse") && (
          <Button onClick={() => store.set({ askOpen: true })}>
            <MessageSquareText /> Ask
          </Button>
        )}
        <ThemeToggle />
        <button
          type="button"
          onClick={() => store.set({ paletteOpen: true })}
          className="rounded-md px-1 transition-[scale] duration-150 active:scale-[0.96]"
          aria-label="Open command palette"
        >
          <Kbd>⌘K</Kbd>
        </button>
      </div>
    </header>
  );
}
