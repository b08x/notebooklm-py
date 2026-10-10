import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogTitle } from "@/components/ui/alert-dialog";
import { post } from "@/lib/api";
import type { DeletePreview } from "@/lib/types";
import { fmt } from "@/lib/utils";
import { store, useApp } from "@/state/store";
import { scheduleDelete } from "./deletes";

const ROWS: [keyof DeletePreview["counts"], string][] = [
  ["clauses", "Clauses"],
  ["embeddings", "Embeddings"],
  ["fact_checks", "Fact-checks"],
  ["parents", "Parent chunks"],
  ["runs", "Runs"],
];

/** Confirm-before-delete: shows what would be removed; only Confirm deletes. */
export function DeleteDialog() {
  const req = useApp((s) => s.deleteRequest);
  const qc = useQueryClient();
  const preview = useQuery({
    queryKey: ["delete-preview", req?.level, req?.ids],
    queryFn: () => post<DeletePreview>("/v1/corpus/delete/preview", { level: req?.level, ids: req?.ids }),
    enabled: !!req,
    gcTime: 0,
  });
  const close = () => store.set({ deleteRequest: null });
  const counts = preview.data?.counts;
  return (
    <AlertDialog open={!!req} onOpenChange={(open) => !open && close()}>
      <AlertDialogContent aria-describedby="delete-desc">
        <AlertDialogTitle>
          Delete {req?.level === "clause" && (req?.ids.length ?? 0) > 1 ? `${req?.ids.length} chunks` : req?.label}?
        </AlertDialogTitle>
        <AlertDialogDescription id="delete-desc">
          Level: <b className="text-fg">{req?.level}</b>. This permanently removes the rows below from the local
          corpus and records each delete in the removal log.
        </AlertDialogDescription>
        <dl className="grid grid-cols-[1fr_auto] gap-x-6 gap-y-1 rounded-lg bg-surface-2/60 p-3 text-[13px]" data-testid="delete-counts">
          {ROWS.filter(([k]) => !counts || counts[k] > 0 || k === "clauses" || k === "embeddings" || k === "fact_checks").map(([k, label]) => (
            <div key={k} className="contents">
              <dt className="text-muted">{label}</dt>
              <dd className="m-0 text-right font-medium tabular">{counts ? fmt.format(counts[k]) : "…"}</dd>
            </div>
          ))}
        </dl>
        {preview.isError && <p className="text-[12.5px] text-bad">Could not count the rows: {(preview.error as Error).message}</p>}
        <div className="flex justify-end gap-2">
          <AlertDialogCancel>Cancel</AlertDialogCancel>
          <AlertDialogAction
            disabled={!counts}
            onClick={() => {
              if (req) scheduleDelete(qc, req);
              close();
            }}
          >
            Delete
          </AlertDialogAction>
        </div>
      </AlertDialogContent>
    </AlertDialog>
  );
}
