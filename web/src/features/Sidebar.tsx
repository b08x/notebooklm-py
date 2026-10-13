import {
  ChevronLeft,
  ChevronRight,
} from "lucide-react";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Tooltip } from "@/components/ui/tooltip";
import { Drawer } from "@/features/Drawer";
import { useViewportTier } from "@/hooks/useViewportTier";
import { BP_SIDEBAR_DEFAULT } from "@/lib/layout";
import { cn } from "@/lib/utils";
import { TABS, actions, store, useApp } from "@/state/store";

export const SIDEBAR_STORAGE_KEY = "corpus-explorer:sidebar-collapsed";

export function getInitialCollapsed(): boolean {
  if (typeof window === "undefined") return true;
  const stored = localStorage.getItem(SIDEBAR_STORAGE_KEY);
  if (stored !== null) {
    return stored === "true";
  }
  return window.innerWidth < BP_SIDEBAR_DEFAULT;
}

interface SidebarNavProps {
  collapsed: boolean;
  onItemClick?: () => void;
  showToggle?: boolean;
  onToggle?: () => void;
}

function SidebarNav({ collapsed, onItemClick, showToggle, onToggle }: SidebarNavProps) {
  const currentTab = useApp((s) => s.tab);

  return (
    <div className="flex h-full flex-col justify-between">
      <div>
        {/* Header / Brand */}
        <div className={cn("flex h-10 items-center px-3 border-b border-line", collapsed ? "justify-center" : "gap-2.5")}>
          <div
            className="size-5 shrink-0 rounded-md bg-gradient-to-br from-[#a78bfa] to-[#7dd3fc] grid place-items-center text-[10px] font-bold text-white shadow-sm"
            aria-hidden
          >
            CE
          </div>
          {!collapsed && (
            <span className="text-[13px] font-semibold text-fg tracking-tight truncate">
              Corpus Explorer
            </span>
          )}
        </div>

        {/* Navigation list */}
        <nav aria-label="Views" className="p-2 space-y-1">
          {TABS.map((t) => {
            const Icon = t.icon;
            const active = currentTab === t.id;
            const button = (
              <button
                key={t.id}
                type="button"
                data-testid={`sidebar-tab-${t.id}`}
                aria-current={active ? "page" : undefined}
                onClick={() => {
                  actions.setTab(t.id);
                  onItemClick?.();
                }}
                className={cn(
                  "flex w-full items-center rounded-lg py-2 text-[13px] font-medium transition-[color,background-color,scale] duration-150 active:scale-[0.96]",
                  collapsed ? "justify-center px-0" : "gap-3 px-2.5",
                  active
                    ? "bg-surface-2 text-fg shadow-xs"
                    : "text-muted hover:bg-surface-2/60 hover:text-fg",
                )}
              >
                <Icon className="size-4 shrink-0 text-muted" aria-hidden />
                {!collapsed && <span className="truncate">{t.label}</span>}
              </button>
            );

            if (collapsed) {
              return (
                <Tooltip key={t.id} content={t.label} side="right">
                  {button}
                </Tooltip>
              );
            }
            return button;
          })}
        </nav>
      </div>

      {/* Footer with collapse toggle button */}
      {showToggle && onToggle && (
        <div className="p-2 border-t border-line">
          {collapsed ? (
            <Tooltip content="Expand sidebar (256px)" side="right">
              <Button
                variant="ghost"
                size="icon"
                aria-label="Expand sidebar"
                data-testid="sidebar-toggle"
                onClick={onToggle}
                className="w-full h-8 rounded-lg text-muted hover:text-fg hover:bg-surface-2 active:scale-[0.96]"
              >
                <ChevronRight className="size-4" />
              </Button>
            </Tooltip>
          ) : (
            <button
              type="button"
              aria-label="Collapse sidebar"
              data-testid="sidebar-toggle"
              onClick={onToggle}
              className="flex w-full items-center gap-3 rounded-lg px-2.5 py-1.5 text-[12px] text-muted hover:bg-surface-2 hover:text-fg active:scale-[0.96] transition-[color,background-color,scale] duration-150"
            >
              <ChevronLeft className="size-4 shrink-0" />
              <span className="truncate">Collapse sidebar</span>
            </button>
          )}
        </div>
      )}
    </div>
  );
}

export function Sidebar() {
  const tier = useViewportTier();
  const drawerOpen = useApp((s) => s.sidebarDrawerOpen);
  const [collapsed, setCollapsed] = useState(getInitialCollapsed);

  useEffect(() => {
    // If user has not stored a preference, update on resize around 1280px
    if (localStorage.getItem(SIDEBAR_STORAGE_KEY) === null && typeof window !== "undefined") {
      setCollapsed(window.innerWidth < BP_SIDEBAR_DEFAULT);
    }
  }, [tier]);

  const toggle = () => {
    setCollapsed((prev) => {
      const next = !prev;
      localStorage.setItem(SIDEBAR_STORAGE_KEY, String(next));
      return next;
    });
  };

  // Tiny tier (< 768px): sidebar becomes a left drawer
  if (tier === "tiny") {
    return (
      <Drawer
        open={drawerOpen}
        onOpenChange={(open) => store.set({ sidebarDrawerOpen: open })}
        side="left"
        width={256}
        title="Navigation"
      >
        <SidebarNav
          collapsed={false}
          onItemClick={() => store.set({ sidebarDrawerOpen: false })}
          showToggle={false}
        />
      </Drawer>
    );
  }

  return (
    <aside
      aria-label="Sidebar"
      data-testid="sidebar"
      style={{ width: collapsed ? 64 : 256 }}
      className={cn(
        "h-full shrink-0 border-r border-line bg-surface select-none transition-[width] duration-150 overflow-hidden flex flex-col",
      )}
    >
      <SidebarNav
        collapsed={collapsed}
        showToggle
        onToggle={toggle}
      />
    </aside>
  );
}
