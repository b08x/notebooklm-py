import { DatabaseZap, RotateCw } from "lucide-react";
import { Button } from "@/components/ui/button";

/** Blocking screen while Postgres is unreachable — never an empty corpus. */
export function DbDown({ onRetry, checking }: { onRetry: () => void; checking: boolean }) {
  return (
    <div role="alertdialog" aria-label="Database unreachable" className="grid h-full place-items-center bg-bg p-6">
      <div className="grid max-w-md gap-3 text-center">
        <DatabaseZap className="mx-auto size-7 text-bad" />
        <h1 className="text-[16px] font-semibold">Database unreachable</h1>
        <p className="text-[13px] text-muted">
          The corpus lives in Postgres and the server cannot reach it. Start it (for example{" "}
          <code className="font-mono text-[12px]">docker compose -f deploy/docker-compose.db.yml up -d</code>) and retry.
          Nothing is shown until then, so an outage never looks like an empty corpus.
        </p>
        <Button variant="primary" size="md" className="mx-auto" onClick={onRetry} disabled={checking}>
          <RotateCw className={checking ? "animate-spin" : ""} /> Retry
        </Button>
      </div>
    </div>
  );
}
