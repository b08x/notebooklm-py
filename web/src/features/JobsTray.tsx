import * as Popover from "@radix-ui/react-popover";
import { CircleCheck, CircleX, ExternalLink, Loader2, PanelTop } from "lucide-react";
import { useEffect, useState, useSyncExternalStore } from "react";
import { Badge } from "@/components/ui/badge";
import { fmt, formatElapsed } from "@/lib/utils";
import { type TrackedJob, subscribeJobs, trackedJobs } from "@/state/jobs";

/** Jobs popover for the status footer: active jobs first, then recent, with traces. */
export function JobsTray() {
  const jobs = useSyncExternalStore(subscribeJobs, trackedJobs, trackedJobs);
  const [open, setOpen] = useState(false);
  const [now, setNow] = useState(Date.now());
  const active = jobs.filter((j) => j.status === "queued" || j.status === "running");

  useEffect(() => {
    if (!open || !active.length) return;
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, [open, active.length]);

  return (
    <Popover.Root open={open} onOpenChange={setOpen}>
      <Popover.Trigger
        className="flex items-center rounded-md px-1 transition-[color,scale] duration-150 hover:text-fg active:scale-[0.96]"
        aria-label="Jobs"
        data-testid="jobs-tray-trigger"
      >
        <PanelTop className="size-3" />
        jobs
        {active.length > 0 && (
          <span
            className="ml-1 inline-flex h-[15px] min-w-[15px] items-center justify-center rounded-[8px] bg-primary px-1 font-mono text-[10px] text-primary-fg"
            data-testid="jobs-badge"
          >
            {active.length}
          </span>
        )}
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content
          side="top"
          align="end"
          sideOffset={6}
          className="z-50 max-h-80 w-96 overflow-auto rounded-xl bg-surface p-1.5 shadow-pop ring-1 ring-line"
          data-testid="jobs-tray"
        >
          {jobs.length === 0 && <p className="p-3 text-[12.5px] text-muted">No jobs yet.</p>}
          {jobs.map((j) => (
            <TrayRow key={j.id} job={j} now={now} />
          ))}
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}

function TrayRow({ job, now }: { job: TrackedJob; now: number }) {
  const running = job.status === "queued" || job.status === "running";
  const end = job.finished_at ? job.finished_at * 1000 : now;
  const elapsed = Math.max(0, (end - job.startedMs) / 1000);
  return (
    <div
      className="grid grid-cols-[16px_minmax(0,1fr)_auto] items-center gap-2 rounded-lg px-2 py-1.5 text-[12.5px] transition-[background-color] duration-150 hover:bg-surface-2/60"
      data-testid={`jobs-row-${job.id}`}
    >
      {running ? (
        <Loader2 className="size-3.5 animate-spin text-primary" />
      ) : job.status === "done" ? (
        <CircleCheck className="size-3.5 text-ok" />
      ) : (
        <CircleX className="size-3.5 text-bad" />
      )}
      <div className="min-w-0">
        <div className="flex items-center gap-1.5">
          <Badge tone={running ? "info" : job.status === "done" ? "ok" : "bad"}>{job.kind}</Badge>
          <span className="truncate" title={job.label}>{job.label}</span>
        </div>
        <div className="truncate text-[11.5px] text-muted" data-testid={`jobs-message-${job.id}`}>
          {job.error ? job.error : job.message || job.status}
          {job.total > 0 && ` · ${fmt.format(job.done)}/${fmt.format(job.total)}`}
          {` · ${formatElapsed(elapsed)}`}
        </div>
      </div>
      {job.trace_url && (
        <a
          href={job.trace_url}
          target="_blank"
          rel="noreferrer"
          onClick={(e) => e.stopPropagation()}
          className="inline-flex items-center gap-0.5 text-[12px] text-secondary transition-[color] duration-150 hover:underline"
          data-testid={`jobs-trace-${job.id}`}
        >
          trace <ExternalLink className="size-3" />
        </a>
      )}
    </div>
  );
}
