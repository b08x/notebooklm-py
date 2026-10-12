import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import type * as React from "react";
import { vi } from "vitest";
import { TooltipProvider } from "@/components/ui/tooltip";
import { resetJobs } from "@/state/jobs";
import { resetStore } from "@/state/store";

export interface Call {
  method: string;
  path: string;
  body: unknown;
}

type Handler = (call: Call) => unknown;
export type Routes = Record<string, Handler | object>;

/** ``data:`` lines for an SSE body. */
export function sse(events: object[]): string {
  return events.map((e) => `id: ${(e as { seq?: number }).seq ?? ""}\nevent: ${(e as { type?: string }).type}\ndata: ${JSON.stringify(e)}\n\n`).join("");
}

export class SseBody {
  constructor(public text: string) {}
}

export class Status {
  constructor(public status: number, public body: unknown) {}
}

/**
 * Replace ``fetch`` with a router keyed ``"METHOD /path"`` (query string ignored).
 * A handler may return JSON, ``Status`` for an error, or ``SseBody`` for a stream.
 */
export function mockFetch(routes: Routes): Call[] {
  const calls: Call[] = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), "http://localhost");
    const method = (init?.method ?? "GET").toUpperCase();
    const body = init?.body ? JSON.parse(String(init.body)) : undefined;
    const call = { method, path: url.pathname + url.search, body };
    calls.push(call);
    const key = `${method} ${decodeURIComponent(url.pathname)}`;
    const route = routes[key];
    if (route === undefined) return new Response(JSON.stringify({ error: { category: "not_found", message: key } }), { status: 404 });
    const out = typeof route === "function" ? await (route as Handler)(call) : route;
    if (out instanceof Status) return new Response(JSON.stringify(out.body), { status: out.status, headers: { "content-type": "application/json" } });
    if (out instanceof SseBody) {
      const stream = new ReadableStream({
        start(controller) {
          controller.enqueue(new TextEncoder().encode(out.text));
          controller.close();
        },
      });
      return new Response(stream, { status: 200, headers: { "content-type": "text/event-stream" } });
    }
    return new Response(JSON.stringify(out), { status: 200, headers: { "content-type": "application/json" } });
  });
  return calls;
}

export function renderWithClient(ui: React.ReactElement) {
  resetStore();
  resetJobs();
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  return {
    client,
    ...render(
      <QueryClientProvider client={client}>
        <TooltipProvider>{ui}</TooltipProvider>
      </QueryClientProvider>,
    ),
  };
}

export const row = (over: Partial<Record<string, unknown>> = {}) => ({
  id: 1,
  external_id: "doc:1:0",
  text: "Kernel panics hit the cgroup memory limit.",
  document_id: "doc",
  run_id: 1,
  parent_id: 10,
  sentence_index: 0,
  notebook_id: "nb",
  strategy: "recursive",
  kind: "source",
  title: "Doc",
  is_active: true,
  length: 42,
  quality: "clean",
  fact_check: "unchecked",
  has_sfl: false,
  ...over,
});
