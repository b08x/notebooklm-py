import { useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import { onJobFinished } from "./jobs";

/** Query keys a finished job can change (SFL tags, ingest). */
export const JOB_INVALIDATED_KEYS = ["stats", "facets", "browse", "search", "chunk", "runs"] as const;

/** Refresh whatever view is open once a job finishes. Mounted once at the app root. */
export function useJobInvalidation(): void {
  const qc = useQueryClient();
  useEffect(
    () =>
      onJobFinished(() => {
        for (const key of JOB_INVALIDATED_KEYS) void qc.invalidateQueries({ queryKey: [key] });
      }),
    [qc],
  );
}
