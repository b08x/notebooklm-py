import { useQueryClient } from "@tanstack/react-query";
import { AudioLines, CheckCircle2, FileText, ImageOff, KeyRound, Loader2, Video } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { SectionLabel } from "@/components/ui/section-label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { followEvents, post } from "@/lib/api";
import { useArtifacts, useNotebooks, useProviders } from "@/lib/queries";
import type { ArtifactRow, JobSnapshot, Provider } from "@/lib/types";
import { cn, shortId } from "@/lib/utils";
import { store, useApp } from "@/state/store";

export const LANGUAGES: [string, string][] = [
  ["auto", "Auto-detect"],
  ["en", "English"],
  ["de", "German"],
  ["fr", "French"],
  ["es", "Spanish"],
  ["it", "Italian"],
  ["pt", "Portuguese"],
  ["nl", "Dutch"],
  ["ja", "Japanese"],
  ["zh", "Chinese"],
];

function KindIcon({ a }: { a: ArtifactRow }) {
  if (!a.ingestible && a.media === "image") return <ImageOff className="size-3.5 text-subtle" />;
  if (a.media === "audio") return <AudioLines className="size-3.5" />;
  if (a.media === "video") return <Video className="size-3.5" />;
  return <FileText className="size-3.5" />;
}

/** Provider choice, key status line, Diarize and Language — the audio-segment-extractor panel. */
export function TranscriptionPanel({
  providers,
  provider,
  setProvider,
  diarize,
  setDiarize,
  language,
  setLanguage,
}: {
  providers: Provider[];
  provider: string;
  setProvider: (p: string) => void;
  diarize: boolean;
  setDiarize: (d: boolean) => void;
  language: string;
  setLanguage: (l: string) => void;
}) {
  const chosen = providers.find((p) => p.id === provider);
  return (
    <div className="grid gap-3 rounded-lg bg-surface-2/50 p-3" data-testid="transcription-panel">
      <div>
        <SectionLabel>Provider</SectionLabel>
        <RadioGroup value={provider} onValueChange={setProvider} className="grid grid-cols-2 gap-1.5" aria-label="Transcription provider">
          {providers.map((p) => (
            <label key={p.id} className="flex items-center gap-2 rounded-md px-1.5 py-1 text-[13px] hover:bg-surface">
              <RadioGroupItem value={p.id} aria-label={p.label} />
              {p.label}
            </label>
          ))}
        </RadioGroup>
        {chosen && (
          <p
            data-testid="key-status"
            className={cn("mt-1.5 flex items-center gap-1.5 font-mono text-[11.5px]", chosen.key_present ? "text-ok" : "text-bad")}
          >
            <KeyRound className="size-3" />
            {chosen.key_present ? "key found" : "key missing"} · {chosen.env_var}
          </p>
        )}
      </div>
      <div className="flex items-center gap-4">
        <label className="flex items-center gap-2 text-[13px]">
          <Switch checked={diarize} onCheckedChange={setDiarize} aria-label="Diarize" />
          Diarize
        </label>
        <div className="ml-auto w-40">
          <Select value={language} onValueChange={setLanguage}>
            <SelectTrigger aria-label="Language">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {LANGUAGES.map(([code, label]) => (
                <SelectItem key={code} value={code}>
                  {label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>
    </div>
  );
}

export function IngestDialog() {
  const open = useApp((s) => s.ingestOpen);
  const qc = useQueryClient();
  const notebooks = useNotebooks();
  const [notebookId, setNotebookId] = useState<string | null>(null);
  const artifacts = useArtifacts(open ? notebookId : null);
  const providersQ = useProviders();
  const [artifactId, setArtifactId] = useState<string | null>(null);
  const [provider, setProvider] = useState("deepgram");
  const [diarize, setDiarize] = useState(true);
  const [language, setLanguage] = useState("auto");
  const [force, setForce] = useState(false);
  const [job, setJob] = useState<JobSnapshot | null>(null);

  useEffect(() => {
    const d = providersQ.data?.defaults;
    if (d) {
      setProvider(d.provider);
      setDiarize(d.diarize);
      setLanguage(d.language || "auto");
    }
  }, [providersQ.data]);
  useEffect(() => {
    if (!notebookId && notebooks.data?.items.length) setNotebookId(notebooks.data.items[0].id);
  }, [notebooks.data, notebookId]);

  const artifact = useMemo(() => artifacts.data?.items.find((a) => a.id === artifactId) ?? null, [artifacts.data, artifactId]);
  const isMedia = artifact?.media === "audio" || artifact?.media === "video";
  const running = job?.status === "running" || job?.status === "queued";

  const start = async () => {
    if (!artifact || !notebookId) return;
    const snap = await post<JobSnapshot>(`/v1/corpus/artifacts/${encodeURIComponent(artifact.id)}/ingest`, {
      notebook_id: notebookId,
      provider: isMedia ? provider : undefined,
      diarize: isMedia ? diarize : undefined,
      language: isMedia ? language : undefined,
      force,
    });
    setJob(snap);
    const ctl = new AbortController();
    await followEvents(
      `/v1/corpus/jobs/${snap.id}/events`,
      (ev) => {
        if (ev.type === "progress") setJob((j) => (j ? { ...j, message: String(ev.message) } : j));
        if (ev.type === "finished") {
          const result = ev.result as { status?: string; n_children?: number } | null;
          const message =
            ev.status !== "done"
              ? `Ingest failed: ${String(ev.error)}`
              : result?.status === "skipped_unchanged"
                ? "Already ingested, unchanged"
                : `Ingested ${result?.n_children ?? 0} chunks`;
          setJob((j) =>
            j ? { ...j, status: ev.status as JobSnapshot["status"], result: ev.result as JobSnapshot["result"], error: ev.error as string | null, message } : j,
          );
          if (ev.status === "done") toast.success(message);
          else toast.error(message);
          void qc.invalidateQueries();
        }
      },
      { signal: ctl.signal, isFinal: (ev) => ev.type === "finished" },
    );
  };

  return (
    <Dialog open={open} onOpenChange={(o) => store.set({ ingestOpen: o })}>
      <DialogContent className="w-[min(560px,calc(100vw-32px))]" aria-describedby="ingest-desc">
        <DialogTitle>Ingest a NotebookLM artifact</DialogTitle>
        <DialogDescription id="ingest-desc" className="mb-3">
          Adds the artifact to the corpus as its own document. Unchanged content is skipped by checksum.
        </DialogDescription>
        <div className="grid gap-3">
          <Select value={notebookId ?? undefined} onValueChange={(v) => { setNotebookId(v); setArtifactId(null); }}>
            <SelectTrigger aria-label="Notebook">
              <SelectValue placeholder="Notebook" />
            </SelectTrigger>
            <SelectContent>
              {(notebooks.data?.items ?? []).map((n) => (
                <SelectItem key={n.id} value={n.id}>
                  {n.title ?? shortId(n.id, 24)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <div className="max-h-56 overflow-auto rounded-lg shadow-[inset_0_0_0_1px_var(--line)]" role="listbox" aria-label="Artifacts">
            {artifacts.isLoading && <p className="p-3 text-[12.5px] text-muted">Loading artifacts…</p>}
            {artifacts.isError && <p className="p-3 text-[12.5px] text-bad">Could not list artifacts (is NotebookLM signed in?).</p>}
            {(artifacts.data?.items ?? []).map((a) => (
              <button
                type="button"
                role="option"
                aria-selected={artifactId === a.id}
                aria-disabled={!a.ingestible}
                disabled={!a.ingestible}
                key={a.id}
                onClick={() => setArtifactId(a.id)}
                className={cn(
                  "flex w-full items-center gap-2 border-b border-line/60 px-3 py-2 text-left text-[13px] transition-[background-color] duration-150 last:border-0",
                  a.ingestible ? "hover:bg-surface-2/60 active:bg-surface-2" : "cursor-not-allowed text-subtle",
                  artifactId === a.id && "bg-selection shadow-[inset_2px_0_0_var(--primary)]",
                )}
              >
                <KindIcon a={a} />
                <span className="min-w-0 flex-1 truncate">{a.title}</span>
                {a.ingested && <Badge tone="ok"><CheckCircle2 className="size-3" /> ingested</Badge>}
                {a.reason ? <span className="text-[11.5px]">{a.reason}</span> : <Badge>{a.kind.replace("_", " ")}</Badge>}
              </button>
            ))}
          </div>
          {artifact && isMedia && providersQ.data && (
            <TranscriptionPanel
              providers={providersQ.data.providers}
              provider={provider}
              setProvider={setProvider}
              diarize={diarize}
              setDiarize={setDiarize}
              language={language}
              setLanguage={setLanguage}
            />
          )}
          {job && (
            <p role="status" className="flex items-center gap-2 text-[12.5px] text-muted">
              {running && <Loader2 className="size-3.5 animate-spin" />}
              {job.status === "failed" ? <span className="text-bad">{job.message}</span> : job.message || job.status}
            </p>
          )}
          <div className="flex items-center gap-2">
            <label className="flex items-center gap-2 text-[12.5px] text-muted">
              <Checkbox checked={force} onCheckedChange={(v) => setForce(v === true)} aria-label="Force re-ingest" />
              Force re-ingest
            </label>
            <Button
              variant="primary"
              size="md"
              className="ml-auto"
              disabled={!artifact || running}
              onClick={() => void start().catch((e: Error) => toast.error(e.message))}
            >
              {isMedia ? "Transcribe" : "Ingest"}
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
