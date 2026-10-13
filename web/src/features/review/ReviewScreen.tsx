import { Drawer } from "@/features/Drawer";
import { DocumentList } from "@/features/review/DocumentList";
import { DocumentView } from "@/features/review/DocumentView";
import { Inspector } from "@/features/review/Inspector";
import { useViewportTier } from "@/hooks/useViewportTier";
import { store, useApp } from "@/state/store";

export function ReviewScreen() {
  const tier = useViewportTier();
  const listDrawerOpen = useApp((s) => s.listDrawerOpen);

  const isListDrawer = tier === "tiny" || tier === "narrow";

  return (
    <div
      data-testid="review-screen"
      className="flex flex-1 min-h-0 min-w-0 overflow-hidden relative bg-bg"
    >
      {/* Document List: Inline on wide & medium (>=1024px), Drawer on narrow & tiny (<1024px) */}
      {isListDrawer ? (
        <Drawer
          open={listDrawerOpen}
          onOpenChange={(open) => store.set({ listDrawerOpen: open })}
          side="left"
          width={320}
          title="Document list"
        >
          <DocumentList
            className="w-full min-w-full max-w-full border-r-0"
            onSelectDoc={() => store.set({ listDrawerOpen: false })}
          />
        </Drawer>
      ) : (
        <DocumentList />
      )}

      {/* Document View: Takes remaining width, min-w-0, scrolls on its own */}
      <DocumentView />

      {/* Inspector: Inline on wide (>=1400px), Drawer on medium/narrow/tiny (<1400px) */}
      <Inspector />
    </div>
  );
}
