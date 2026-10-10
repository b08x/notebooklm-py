import { describe, expect, it, vi } from "vitest";
import { mockFetch, SseBody, Status, sse } from "@/test/utils";
import { ApiError, followEvents, get, onApiError, readSse, withQuery } from "./api";
import { queryTerms } from "./highlight";
import { applyTheme, currentTheme, toggleTheme } from "./theme";
import { clauseNumber, formatElapsed, shortId } from "./utils";

describe("api", () => {
  it("builds query strings with repeated keys and skips empty values", () => {
    expect(withQuery("/x", { a: ["1", "2"], b: undefined, c: "", d: 0, e: true })).toBe("/x?a=1&a=2&d=0&e=true");
    expect(withQuery("/x")).toBe("/x");
  });

  it("sends the bearer token and raises typed errors to listeners", async () => {
    localStorage.setItem("ce-token", "tok");
    const spy = vi.fn();
    const off = onApiError(spy);
    const calls = mockFetch({ "GET /v1/x": new Status(503, { error: { category: "database_unreachable", message: "down" } }) });
    await expect(get("/v1/x")).rejects.toMatchObject({ status: 503, category: "database_unreachable" });
    expect(spy.mock.calls[0][0]).toBeInstanceOf(ApiError);
    off();
    expect(calls).toHaveLength(1);
    const [, init] = vi.mocked(fetch).mock.calls[0];
    expect((init?.headers as Record<string, string>).Authorization).toBe("Bearer tok");
  });

  it("parses SSE blocks split across chunks, skipping comments", async () => {
    const enc = new TextEncoder();
    const parts = [": keep-alive\n\nid: 1\nevent: a\nda", 'ta: {"x":1}\n\nevent: b\ndata: {"y":2}\n\n'];
    const stream = new ReadableStream({
      start(c) {
        parts.forEach((p) => c.enqueue(enc.encode(p)));
        c.close();
      },
    });
    const out = [];
    for await (const ev of readSse(stream)) out.push(ev);
    expect(out).toEqual([
      { event: "a", id: "1", data: { x: 1 } },
      { event: "b", data: { y: 2 } },
    ]);
  });

  it("followEvents reconnects from the last seq after a dropped stream", async () => {
    let n = 0;
    const calls = mockFetch({
      "GET /v1/run/events": () => {
        n += 1;
        // First connection drops mid-event 2; the second resumes after seq 1.
        return n === 1
          ? new SseBody(sse([{ seq: 1, type: "a" }, { seq: 2, type: "b" }]).slice(0, -1))
          : new SseBody(sse([{ seq: 2, type: "b" }, { seq: 3, type: "run_finished" }]));
      },
    });
    const seen: unknown[] = [];
    await followEvents("/v1/run/events", (d) => seen.push(d.seq), {
      signal: new AbortController().signal,
      isFinal: (d) => d.type === "run_finished",
      retryMs: 1,
    });
    expect(seen).toEqual([1, 2, 3]);
    expect(calls.map((c) => c.path)).toEqual(["/v1/run/events?after=0", "/v1/run/events?after=1"]);
    // Without isFinal a clean close ends following.
    await followEvents("/v1/run/events", (d) => seen.push(d.seq), { signal: new AbortController().signal, after: 3 });
    expect(calls).toHaveLength(3);
  });

  it("followEvents retries on network errors and stops when aborted", async () => {
    let n = 0;
    vi.spyOn(globalThis, "fetch").mockImplementation(async () => {
      n += 1;
      if (n === 1) throw new TypeError("network");
      return new Response(new ReadableStream({ start: (c) => { c.enqueue(new TextEncoder().encode(sse([{ seq: 5, type: "run_finished" }]))); c.close(); } }));
    });
    const seen: unknown[] = [];
    await followEvents("/v1/e", (d) => seen.push(d.seq), { signal: new AbortController().signal, isFinal: () => true, retryMs: 1 });
    expect(seen).toEqual([5]);
    const ctl = new AbortController();
    ctl.abort();
    await followEvents("/v1/e", () => {}, { signal: ctl.signal });
  });
});

describe("theme (facts 7-8)", () => {
  it("flips instantly with transitions suppressed for one frame, and persists", async () => {
    document.documentElement.classList.add("dark");
    expect(currentTheme()).toBe("dark");
    applyTheme("light");
    expect(document.documentElement.classList.contains("theme-switching")).toBe(true);
    expect(currentTheme()).toBe("light");
    expect(localStorage.getItem("ce-theme")).toBe("light");
    await new Promise((r) => requestAnimationFrame(() => r(null)));
    expect(document.documentElement.classList.contains("theme-switching")).toBe(false);
    expect(toggleTheme()).toBe("dark");
  });
});

describe("helpers", () => {
  it("formats ids, elapsed time and query terms", () => {
    expect(shortId("abcdefghijk", 4)).toBe("abcd…");
    expect(shortId(null)).toBe("—");
    expect(clauseNumber("doc:12:7")).toBe("12:7");
    expect(clauseNumber("x")).toBe("x");
    expect(formatElapsed(476)).toBe("07:56");
    expect(queryTerms('"named entity" OR -spaCy the a')).toEqual(["named", "entity", "spacy"]);
  });
});
