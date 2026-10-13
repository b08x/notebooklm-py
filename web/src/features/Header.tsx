import { AnimatePresence, motion } from "motion/react";
import {
  List,
  Menu,
  MessageSquareText,
  Moon,
  PanelRight,
  Search,
  Sun,
} from "lucide-react";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Kbd } from "@/components/ui/kbd";
import { Tooltip } from "@/components/ui/tooltip";
import { Breadcrumbs } from "@/features/Breadcrumbs";
import { useViewportTier } from "@/hooks/useViewportTier";
import { currentTheme, toggleTheme } from "@/lib/theme";
import type { Mode } from "@/lib/types";
import { cn } from "@/lib/utils";
import { store, useApp } from "@/state/store";

const MODES: { id: Mode; label: string }[] = [
  { id: "keyword", label: "Keyword" },
  { id: "vector", label: "Vector" },
  { id: "hybrid", label: "Hybrid · RRF" },
];

function ThemeToggle() {
  const [theme, setTheme] = useState(currentTheme);
  return (
    <Tooltip content="Toggle theme">
      <Button
        variant="ghost"
        size="icon"
        aria-label="Toggle theme"
        onClick={() => setTheme(toggleTheme())}
        className="size-7 rounded-md text-muted hover:text-fg active:scale-[0.96]"
      >
        <AnimatePresence initial={false} mode="popLayout">
          <motion.span
            key={theme}
            initial={{ scale: 0.25, opacity: 0, filter: "blur(4px)" }}
            animate={{ scale: 1, opacity: 1, filter: "blur(0px)" }}
            exit={{ scale: 0.25, opacity: 0, filter: "blur(4px)" }}
            transition={{ type: "spring", duration: 0.3, bounce: 0 }}
            className="grid place-items-center"
          >
            {theme === "dark" ? <Moon className="size-4" /> : <Sun className="size-4" />}
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
  const tier = useViewportTier();

  useEffect(() => {
    const t = setTimeout(() => {
      if (store.get().submittedQuery !== query) store.set({ submittedQuery: query.trim() });
    }, 350);
    return () => clearTimeout(t);
  }, [query]);

  const showSidebarDrawerBtn = tier === "tiny";
  const showListDrawerBtn = tab === "review" && (tier === "tiny" || tier === "narrow");
  const showInspectorDrawerBtn = tab === "review" && tier !== "wide";

  return (
    <header className="flex h-10 items-center gap-2 border-b border-line px-3 bg-surface select-none shrink-0">
      {/* Drawer triggers for responsive modes */}
      {showSidebarDrawerBtn && (
        <Tooltip content="Navigation">
          <Button
            variant="ghost"
            size="icon"
            aria-label="Open navigation drawer"
            data-testid="header-sidebar-drawer-btn"
            onClick={() => store.set({ sidebarDrawerOpen: true })}
            className="size-7 rounded-md text-muted hover:text-fg active:scale-[0.96]"
          >
            <Menu className="size-4" />
          </Button>
        </Tooltip>
      )}

      {showListDrawerBtn && (
        <Tooltip content="Document list">
          <Button
            variant="ghost"
            size="icon"
            aria-label="Open document list drawer"
            data-testid="header-list-drawer-btn"
            onClick={() => store.set({ listDrawerOpen: true })}
            className="size-7 rounded-md text-muted hover:text-fg active:scale-[0.96]"
          >
            <List className="size-4" />
          </Button>
        </Tooltip>
      )}

      {/* Breadcrumbs */}
      <div className="flex-1 min-w-0 flex items-center">
        <Breadcrumbs />
      </div>

      {/* Search bar & mode switch on search screen */}
      {tab === "search" && (
        <>
          <form
            role="search"
            className="flex h-7 max-w-[420px] flex-1 items-center gap-2 rounded-lg bg-surface px-2 shadow-[inset_0_0_0_1px_var(--line)] transition-[box-shadow] duration-150 focus-within:shadow-[inset_0_0_0_1px_var(--primary)]"
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
              className="min-w-0 flex-1 bg-transparent text-[12px] text-fg outline-none placeholder:text-subtle"
            />
            <Kbd>/</Kbd>
          </form>
          <div
            role="radiogroup"
            aria-label="Search mode"
            className="flex rounded-lg bg-surface p-0.5 text-[11px] shadow-[inset_0_0_0_1px_var(--line)]"
          >
            {MODES.map((m) => (
              <button
                key={m.id}
                type="button"
                role="radio"
                aria-checked={mode === m.id}
                onClick={() => store.set({ mode: m.id })}
                className={cn(
                  "rounded-md px-2 py-0.5 text-muted transition-[color,background-color,scale] duration-150 active:scale-[0.96]",
                  mode === m.id && "bg-surface-2 text-fg shadow-[0_1px_2px_#0006]",
                )}
              >
                {m.label}
              </button>
            ))}
          </div>
        </>
      )}

      {/* Actions & chrome on right */}
      <div className="flex items-center gap-1.5 shrink-0">
        {showInspectorDrawerBtn && (
          <Tooltip content="Inspector">
            <Button
              variant="ghost"
              size="icon"
              aria-label="Open inspector drawer"
              data-testid="header-inspector-drawer-btn"
              onClick={() => store.set({ inspectorDrawerOpen: true })}
              className="size-7 rounded-md text-muted hover:text-fg active:scale-[0.96]"
            >
              <PanelRight className="size-4" />
            </Button>
          </Tooltip>
        )}

        {(tab === "search" || tab === "browse") && (
          <Button
            size="sm"
            onClick={() => store.set({ askOpen: true })}
            className="h-7 text-[12px] gap-1.5"
          >
            <MessageSquareText className="size-3.5" /> Ask
          </Button>
        )}

        <ThemeToggle />

        <button
          type="button"
          onClick={() => store.set({ paletteOpen: true })}
          className="rounded-md p-1 text-muted hover:text-fg transition-[scale] duration-150 active:scale-[0.96]"
          aria-label="Open command palette"
        >
          <Kbd>⌘K</Kbd>
        </button>
      </div>
    </header>
  );
}
