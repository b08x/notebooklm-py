import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Toaster } from "sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import { AskDrawer } from "@/features/AskDrawer";
import { Breadcrumbs } from "@/features/Breadcrumbs";
import { CommandPalette } from "@/features/CommandPalette";
import { DbDown } from "@/features/DbDown";
import { DeleteDialog } from "@/features/DeleteDialog";
import { FactCheckView } from "@/features/factcheck/FactCheckView";
import { Header } from "@/features/Header";
import { IngestDialog } from "@/features/IngestDialog";
import { ShortcutSheet } from "@/features/ShortcutSheet";
import { StatusFooter } from "@/features/StatusFooter";
import { TokenGate } from "@/features/TokenGate";
import { Workbench } from "@/features/Workbench";
import { useHotkeys } from "@/hooks/useHotkeys";
import { onApiError } from "@/lib/api";
import { useHealth } from "@/lib/queries";
import { getToken, setToken } from "@/lib/token";
import { useApp } from "@/state/store";
import { useJobInvalidation } from "@/state/useJobInvalidation";

async function tokenStillValid(): Promise<boolean> {
  const token = getToken();
  if (!token) return false;
  try {
    const resp = await fetch("/v1/corpus/health", { headers: { Authorization: `Bearer ${token}` } });
    return resp.status !== 401 && resp.status !== 403;
  } catch {
    return true; // network trouble is not a rejected token
  }
}

function Explorer() {
  const tab = useApp((s) => s.tab);
  const health = useHealth();
  useHotkeys();
  useJobInvalidation();
  return (
    <div className="grid h-full grid-rows-[48px_auto_minmax(0,1fr)_28px] bg-bg text-fg">
      <Header />
      <Breadcrumbs />
      <div className="flex min-h-0 min-w-0 overflow-hidden">{tab === "factcheck" ? <FactCheckView /> : <Workbench />}</div>
      <StatusFooter health={health.data} />
      <DeleteDialog />
      <AskDrawer />
      <IngestDialog />
      <CommandPalette />
      <ShortcutSheet />
    </div>
  );
}

export function App() {
  const qc = useQueryClient();
  const [authed, setAuthed] = useState(() => !!getToken());
  const [rejected, setRejected] = useState(false);
  const [dbDown, setDbDown] = useState(false);
  const health = useHealth(authed);

  useEffect(
    () =>
      onApiError((e) => {
        if (e.status === 401) {
          // A 401 can also mean "the server is not signed in to NotebookLM";
          // only a token the server rejects on a corpus route signs us out.
          void tokenStillValid().then((ok) => {
            if (ok) return;
            setToken(null);
            setRejected(true);
            setAuthed(false);
          });
        } else if (e.status === 503 && e.category === "database_unreachable") {
          setDbDown(true);
        }
      }),
    [],
  );
  useEffect(() => {
    if (health.data && !health.data.postgres.ok) setDbDown(true);
    if (health.data?.postgres.ok && dbDown) {
      setDbDown(false);
      void qc.invalidateQueries();
    }
  }, [health.data, dbDown, qc]);

  return (
    <TooltipProvider delayDuration={300}>
      {!authed ? (
        <TokenGate
          rejected={rejected}
          onSaved={() => {
            setRejected(false);
            setAuthed(true);
            void qc.invalidateQueries();
          }}
        />
      ) : dbDown ? (
        <DbDown checking={health.isFetching} onRetry={() => void health.refetch()} />
      ) : (
        <Explorer />
      )}
      <Toaster theme="system" position="bottom-right" toastOptions={{ className: "!bg-surface !text-fg !ring-1 !ring-line !border-0 !rounded-xl" }} />
    </TooltipProvider>
  );
}
