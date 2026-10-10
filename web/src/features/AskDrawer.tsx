import { AlertTriangle, Loader2, Send } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { ApiError, post, streamSse } from "@/lib/api";
import type { AnswerResult, SearchHit } from "@/lib/types";
import { cn } from "@/lib/utils";
import { store, useApp } from "@/state/store";
import { AnswerText } from "./Answer";

type AskMode = "auto" | "notebooklm" | "agent" | "deep" | "model";
const MODES: { id: AskMode; label: string; hint: string }[] = [
  { id: "auto", label: "Auto", hint: "NotebookLM for one notebook, the corpus agent across notebooks" },
  { id: "notebooklm", label: "NotebookLM", hint: "chat.ask scoped to the cited sources" },
  { id: "agent", label: "Corpus agent", hint: "DSPy ReAct per notebook, merged by MultiChainComparison" },
  { id: "deep", label: "Deep", hint: "dspy.RLM explores every hit (experimental)" },
  { id: "model", label: "Model…", hint: "any litellm model, streamed" },
];
const MODEL_SUGGESTIONS = [
  "openrouter/anthropic/claude-sonnet-4.5",
  "openrouter/google/gemini-2.5-pro",
  "openrouter/openai/gpt-5-mini",
  "ollama_chat/llama3.1",
];

interface State {
  status: "idle" | "running" | "done" | "error";
  answer: string;
  labels: Record<string, string>;
  hits: SearchHit[];
  mode?: string;
  error?: ApiError | Error;
  started?: number;
}

export function AskDrawer() {
  const open = useApp((s) => s.askOpen);
  const selected = useApp((s) => s.selected);
  const submittedQuery = useApp((s) => s.submittedQuery);
  const filters = useApp((s) => s.filters);
  const [question, setQuestion] = useState("");
  const [mode, setMode] = useState<AskMode>("auto");
  const [model, setModel] = useState(() => localStorage.getItem("ce-model") ?? "");
  const [state, setState] = useState<State>({ status: "idle", answer: "", labels: {}, hits: [] });
  const [now, setNow] = useState(Date.now());
  const abort = useRef<AbortController | null>(null);

  useEffect(() => {
    if (open && !question) setQuestion(submittedQuery);
  }, [open, submittedQuery, question]);
  useEffect(() => {
    if (state.status !== "running") return;
    const t = setInterval(() => setNow(Date.now()), 250);
    return () => clearInterval(t);
  }, [state.status]);

  const ask = async () => {
    abort.current?.abort();
    const ctl = new AbortController();
    abort.current = ctl;
    const body = {
      question,
      mode,
      model: mode === "model" ? model : undefined,
      ids: selected.length ? selected : undefined,
      filters,
    };
    setState({ status: "running", answer: "", labels: {}, hits: [], started: Date.now() });
    try {
      if (mode === "model") {
        localStorage.setItem("ce-model", model);
        for await (const ev of streamSse("/v1/corpus/answer", { method: "POST", body, signal: ctl.signal })) {
          const d = ev.data;
          if (d.type === "hits") setState((s) => ({ ...s, hits: d.hits as SearchHit[], labels: d.labels as Record<string, string>, mode: "model" }));
          else if (d.type === "token") setState((s) => ({ ...s, answer: s.answer + String(d.text) }));
          else if (d.type === "done") setState((s) => ({ ...s, status: "done" }));
          else if (d.type === "error") setState((s) => ({ ...s, status: "error", error: new Error(String(d.message)) }));
        }
        setState((s) => (s.status === "running" ? { ...s, status: "done" } : s));
      } else {
        const out = await post<AnswerResult>("/v1/corpus/answer", body);
        setState({ status: "done", answer: out.answer, labels: out.labels, hits: out.hits, mode: out.mode });
      }
    } catch (e) {
      if (ctl.signal.aborted) return;
      setState((s) => ({ ...s, status: "error", error: e as Error }));
    }
  };

  const err = state.error;
  const deepUnavailable = err instanceof ApiError && err.category === "deep_mode_unavailable";
  return (
    <Dialog open={open} onOpenChange={(o) => store.set({ askOpen: o })}>
      <DialogContent side="right" aria-describedby="ask-desc">
        <div className="flex h-full flex-col">
          <div className="border-b border-line p-4 pr-10">
            <DialogTitle>Ask over {selected.length ? `${selected.length} selected chunks` : "search results"}</DialogTitle>
            <DialogDescription id="ask-desc">Answers cite the retrieved chunks as [C1]…[Cn]; click one to open it.</DialogDescription>
          </div>
          <form
            className="grid gap-2.5 border-b border-line p-4"
            onSubmit={(e) => {
              e.preventDefault();
              if (question.trim()) void ask();
            }}
          >
            <div role="radiogroup" aria-label="Answer mode" className="flex flex-wrap gap-1 rounded-lg bg-surface-2/60 p-0.5">
              {MODES.map((m) => (
                <button
                  type="button"
                  role="radio"
                  aria-checked={mode === m.id}
                  key={m.id}
                  title={m.hint}
                  onClick={() => setMode(m.id)}
                  className={cn(
                    "rounded-md px-2.5 py-1 text-[12px] text-muted transition-[background-color,color,scale] duration-150 active:scale-[0.96]",
                    mode === m.id && "bg-surface text-fg shadow-[0_1px_2px_#0006]",
                  )}
                >
                  {m.label}
                  {m.id === "deep" && <Badge tone="warn" className="ml-1">experimental</Badge>}
                </button>
              ))}
            </div>
            {mode === "model" && (
              <>
                <Input
                  list="ce-models"
                  value={model}
                  onChange={(e) => setModel(e.target.value)}
                  placeholder="litellm model, e.g. openrouter/anthropic/claude-sonnet-4.5"
                  aria-label="Model"
                />
                <datalist id="ce-models">
                  {MODEL_SUGGESTIONS.map((m) => (
                    <option key={m} value={m} />
                  ))}
                </datalist>
              </>
            )}
            <div className="flex gap-2">
              <Input value={question} onChange={(e) => setQuestion(e.target.value)} placeholder="Ask a question…" aria-label="Question" autoFocus />
              <Button type="submit" variant="primary" size="md" disabled={!question.trim() || state.status === "running" || (mode === "model" && !model.trim())}>
                <Send /> Ask
              </Button>
            </div>
          </form>
          <div className="min-h-0 flex-1 overflow-auto p-4" aria-live="polite">
            {state.status === "running" && !state.answer && (
              <div className="flex items-center gap-2 text-[13px] text-muted" role="status">
                <Loader2 className="size-4 animate-spin" />
                {mode === "model" ? "Waiting for the first token…" : mode === "notebooklm" || mode === "auto" ? "NotebookLM is answering" : "The agent is working"}
                <span className="font-mono text-subtle tabular">· {(((now - (state.started ?? now)) / 1000) | 0)}s</span>
              </div>
            )}
            {state.status === "error" && (
              <div role="alert" className={cn("flex gap-2 rounded-lg p-3 text-[13px]", deepUnavailable ? "bg-warn/10 text-warn" : "bg-bad/10 text-bad")}>
                <AlertTriangle className="mt-0.5 size-4 shrink-0" />
                <span>{deepUnavailable ? `Deep mode unavailable: ${err?.message}` : err?.message}</span>
              </div>
            )}
            {state.answer && (
              <div className="grid gap-3">
                {state.mode && <Badge tone="primary" className="w-fit">{state.mode.replace("_", " ")}</Badge>}
                <AnswerText text={state.answer} labels={state.labels} />
              </div>
            )}
            {state.hits.length > 0 && (
              <div className="mt-5 grid gap-1.5">
                <h4 className="text-[11px] font-semibold tracking-[0.06em] text-subtle uppercase">Grounding chunks</h4>
                {state.hits.map((h, i) => (
                  <button
                    type="button"
                    key={h.external_id}
                    onClick={() => store.set({ detailId: h.external_id })}
                    className="grid grid-cols-[30px_1fr] gap-2 rounded-md p-1 text-left text-[12.5px] text-muted transition-[background-color] duration-150 hover:bg-surface-2 active:bg-line"
                  >
                    <code className="font-mono text-[11px] text-primary">C{i + 1}</code>
                    <span className="line-clamp-2">{h.text}</span>
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
