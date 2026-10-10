import { getToken } from "./token";

export class ApiError extends Error {
  status: number;
  category: string;
  detail: Record<string, unknown>;
  constructor(status: number, category: string, message: string, detail: Record<string, unknown> = {}) {
    super(message);
    this.status = status;
    this.category = category;
    this.detail = detail;
  }
}

type Listener = (error: ApiError) => void;
const listeners = new Set<Listener>();

/** Subscribe to API failures (401 → token prompt, 503 database_unreachable → blocking screen). */
export function onApiError(listener: Listener): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function headers(json: boolean): HeadersInit {
  const h: Record<string, string> = {};
  const token = getToken();
  if (token) h.Authorization = `Bearer ${token}`;
  if (json) h["Content-Type"] = "application/json";
  return h;
}

async function toError(resp: Response): Promise<ApiError> {
  let body: unknown = null;
  try {
    body = await resp.json();
  } catch {
    /* non-JSON error */
  }
  const err = (body as { error?: Record<string, unknown> } | null)?.error ?? {};
  const category = typeof err.category === "string" ? err.category : `http_${resp.status}`;
  const message = typeof err.message === "string" ? err.message : resp.statusText || "Request failed";
  return new ApiError(resp.status, category, message, err);
}

async function raw(path: string, init: RequestInit = {}): Promise<Response> {
  const resp = await fetch(path, init);
  if (!resp.ok) {
    const error = await toError(resp);
    listeners.forEach((l) => l(error));
    throw error;
  }
  return resp;
}

export async function get<T>(path: string, params?: Record<string, unknown>): Promise<T> {
  const resp = await raw(withQuery(path, params), { headers: headers(false) });
  return (await resp.json()) as T;
}

export async function post<T>(path: string, body?: unknown): Promise<T> {
  const resp = await raw(path, {
    method: "POST",
    headers: headers(body !== undefined),
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  return (await resp.json()) as T;
}

export async function postBlob(path: string, body: unknown): Promise<{ blob: Blob; filename: string }> {
  const resp = await raw(path, { method: "POST", headers: headers(true), body: JSON.stringify(body) });
  const disposition = resp.headers.get("content-disposition") ?? "";
  const filename = /filename="([^"]+)"/.exec(disposition)?.[1] ?? "export";
  return { blob: await resp.blob(), filename };
}

export function withQuery(path: string, params?: Record<string, unknown>): string {
  if (!params) return path;
  const qs = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === "") continue;
    if (Array.isArray(value)) value.forEach((v) => qs.append(key, String(v)));
    else qs.append(key, String(value));
  }
  const s = qs.toString();
  return s ? `${path}?${s}` : path;
}

export interface SseEvent {
  event: string;
  data: Record<string, unknown>;
  id?: string;
}

/** Parse a text/event-stream body chunk-by-chunk; yields complete events. */
export async function* readSse(body: ReadableStream<Uint8Array>): AsyncGenerator<SseEvent> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let sep: number;
      while ((sep = buffer.indexOf("\n\n")) >= 0) {
        const block = buffer.slice(0, sep);
        buffer = buffer.slice(sep + 2);
        const ev: SseEvent = { event: "message", data: {} };
        const dataLines: string[] = [];
        for (const line of block.split("\n")) {
          if (line.startsWith(":")) continue;
          if (line.startsWith("event: ")) ev.event = line.slice(7);
          else if (line.startsWith("id: ")) ev.id = line.slice(4);
          else if (line.startsWith("data: ")) dataLines.push(line.slice(6));
        }
        if (dataLines.length) {
          ev.data = JSON.parse(dataLines.join("\n")) as Record<string, unknown>;
          yield ev;
        }
      }
    }
  } finally {
    reader.releaseLock();
  }
}

/** POST (or GET) and iterate the SSE response. */
export async function* streamSse(
  path: string,
  init: { method?: "GET" | "POST"; body?: unknown; signal?: AbortSignal } = {},
): AsyncGenerator<SseEvent> {
  const resp = await raw(path, {
    method: init.method ?? "GET",
    headers: { ...headers(init.body !== undefined), Accept: "text/event-stream" },
    body: init.body === undefined ? undefined : JSON.stringify(init.body),
    signal: init.signal,
  });
  if (!resp.body) return;
  yield* readSse(resp.body);
}

/**
 * EventSource-style follower: streams ``path?after=<seq>`` and, when the
 * connection drops, reconnects from the last seen ``seq`` so nothing is
 * missed or repeated. Stops when ``isFinal`` says so or ``signal`` aborts.
 */
export async function followEvents(
  path: string,
  onEvent: (data: Record<string, unknown>) => void,
  opts: { signal: AbortSignal; after?: number; isFinal?: (data: Record<string, unknown>) => boolean; retryMs?: number },
): Promise<void> {
  let after = opts.after ?? 0;
  while (!opts.signal.aborted) {
    try {
      for await (const ev of streamSse(withQuery(path, { after }), { signal: opts.signal })) {
        const seq = Number(ev.data.seq ?? ev.id ?? after);
        if (seq > after) after = seq;
        onEvent(ev.data);
        if (opts.isFinal?.(ev.data)) return;
      }
      // The stream closed before the final event (proxy timeout, server restart):
      // reconnect from the last seq. Without ``isFinal`` a clean close is the end.
      if (!opts.isFinal) return;
      await new Promise((r) => setTimeout(r, opts.retryMs ?? 1000));
    } catch (e) {
      if (opts.signal.aborted) return;
      if (e instanceof ApiError && e.status < 500) throw e;
      await new Promise((r) => setTimeout(r, opts.retryMs ?? 1000));
    }
  }
}
