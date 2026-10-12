import { CircleCheck, Loader2, Sparkles } from "lucide-react";
import { useEffect, useState, useSyncExternalStore } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { post } from "@/lib/api";
import type { JobSnapshot } from "@/lib/types";
import { cn, formatElapsed } from "@/lib/utils";
import { type TrackedJob, subscribeJobs, trackJob, trackedJobs } from "@/state/jobs";

/** The tracked job with ``id`` — subscribing component for the jobs store. */
export function useTrackedJob(id: string | null): TrackedJob | null {
  useSyncExternalStore(subscribeJobs, trackedJobs, trackedJobs);
  return trackedJobs().find((j) => j.id === id) ?? null;
}

interface Props {
  scope: Record<string, unknown>;
  label: string;
  size?: "sm" | "md" | "icon";
  variant?: "default" | "primary";
  iconOnly?: boolean;
  ariaLabel?: string;
  /** Called once when the job finishes; ``ok`` is false on failure. */
  onDone?: (ok: boolean) => void;
}

/** Post an SFL run and put its job on the shared tracked-jobs store. */
export async function startSflJob(scope: Record<string, unknown>): Promise<JobSnapshot> {
  const snap = await post<JobSnapshot>("/v1/corpus/sfl/runs", { scope });
  trackJob(snap);
  return snap;
}

/** Tag-SFL trigger that follows the job: n/N progress, stage text, elapsed time, error. */
export function TagSflButton({ scope, label, size, variant, iconOnly, ariaLabel, onDone }: Props) {
  const [jobId, setJobId] = useState<string | null>(null);
  const [flash, setFlash] = useState(false);
  const [now, setNow] = useState(Date.now());
  const job = useTrackedJob(jobId);
  const running = job ? job.status === "queued" || job.status === "running" : false;

  useEffect(() => {
    if (!running) return;
    setNow(Date.now());
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, [running]);

  useEffect(() => {
    if (!job || running) return;
    onDone?.(job.status === "done");
    if (job.status === "done" && !flash) {
      setFlash(true);
      const t = setTimeout(() => {
        setFlash(false);
        setJobId(null);
      }, 2000);
      return () => clearTimeout(t);
    }
    return undefined;
    // eslint-disable-next-line react-hooks/exhaustive-deps -- fire once per finished job
  }, [job?.status, running]);

  const start = async () => {
    try {
      const snap = await startSflJob(scope);
      setJobId(snap.id);
    } catch (e) {
      toast.error((e as Error).message);
    }
  };

  if (job && running) {
    const elapsed = Math.max(0, (now - job.startedMs) / 1000);
    const progress = job.total > 0 ? `${job.done}/${job.total}` : "…";
    return (
      <Button
        size={size}
        variant={variant}
        disabled
        aria-label={`Tagging SFL for ${label}`}
        data-testid="tag-sfl-running"
        title={job.message}
      >
        <Loader2 className="animate-spin" />
        {iconOnly ? progress : `${progress} · ${formatElapsed(elapsed)}`}
      </Button>
    );
  }
  if (job && job.status === "failed") {
    return (
      <Button
        size={size}
        variant={variant}
        aria-label={`SFL tagging failed for ${label}`}
        data-testid="tag-sfl-failed"
        title={job.error ?? "SFL tagging failed"}
        className="text-bad"
        onClick={() => {
          setJobId(null);
          void start();
        }}
      >
        <Sparkles />
        {iconOnly ? "failed" : `failed — retry`}
      </Button>
    );
  }
  return (
    <Button
      size={size}
      variant={variant}
      aria-label={ariaLabel ?? `Tag SFL for ${label}`}
      data-testid={flash ? "tag-sfl-done" : "tag-sfl"}
      className={cn(flash && "text-ok")}
      onClick={() => void start()}
    >
      {flash ? <CircleCheck /> : <Sparkles />}
      {iconOnly ? null : flash ? "Tagged" : "Tag SFL"}
    </Button>
  );
}
