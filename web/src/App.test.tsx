import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { App } from "./App";
import { getToken } from "./lib/token";
import { resetStore } from "./state/store";
import { mockFetch, Status } from "./test/utils";

const HEALTHY = {
  postgres: { ok: true, latency_ms: 3 },
  embedder: { ok: false, error: "ConnectError" },
  jobs: [{ id: "j", kind: "ingest", label: "ingest", status: "running", message: "embedding", done: 812, total: 1400, result: null, error: null, document_ids: [], last_seq: 1 }],
  factcheck_runs: [],
};

function renderApp() {
  resetStore();
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <App />
    </QueryClientProvider>,
  );
}

const EMPTY_FACETS = { notebook: [], document: [], run: [], strategy: [], kind: [], fact_check: [], quality: [], length: [] };

describe("App shell", () => {
  it("asks for the token once and keeps it across reloads (fact-3)", async () => {
    mockFetch({
      "GET /v1/corpus/health": (call) => (call ? HEALTHY : HEALTHY),
      "GET /v1/corpus/stats": { clauses: 1, parents: 1, documents: 1, runs: 1, filtered_max_clause_id: 9 },
      "GET /v1/corpus/facets": EMPTY_FACETS,
    });
    const { unmount } = renderApp();
    fireEvent.change(screen.getByLabelText("Server token"), { target: { value: "secret" } });
    fireEvent.click(screen.getByRole("button", { name: /Sign in/ }));
    await screen.findByRole("navigation", { name: "Views" });
    expect(getToken()).toBe("secret");
    unmount();
    renderApp();
    expect(await screen.findByRole("navigation", { name: "Views" })).toBeInTheDocument();
    expect(screen.queryByLabelText("Server token")).toBeNull();
  });

  it("the footer shows Postgres, the embedder and running jobs (fact-9)", async () => {
    localStorage.setItem("ce-token", "t");
    mockFetch({
      "GET /v1/corpus/health": HEALTHY,
      "GET /v1/corpus/stats": { clauses: 1, filtered_max_clause_id: 1 },
      "GET /v1/corpus/facets": EMPTY_FACETS,
    });
    renderApp();
    await waitFor(() => expect(screen.getByTestId("status-postgres")).toHaveTextContent("postgres 3ms"));
    expect(screen.getByTestId("status-embedder")).toHaveTextContent("ollama embed down");
    expect(screen.getByTestId("status-job")).toHaveTextContent("ingest · 812/1,400");
  });

  it("a rejected token returns to the prompt", async () => {
    localStorage.setItem("ce-token", "stale");
    mockFetch({ "GET /v1/corpus/health": new Status(401, { error: { category: "auth", message: "bad token" } }) });
    renderApp();
    expect(await screen.findByLabelText("Server token")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("rejected");
    expect(getToken()).toBeNull();
  });

  it("an unreachable database blocks the UI instead of showing an empty corpus (fact-4)", async () => {
    localStorage.setItem("ce-token", "t");
    mockFetch({
      "GET /v1/corpus/health": { ...HEALTHY, postgres: { ok: false, error: "ConnectionRefusedError" } },
      "GET /v1/corpus/stats": new Status(503, { error: { category: "database_unreachable", message: "down" } }),
      "GET /v1/corpus/facets": new Status(503, { error: { category: "database_unreachable", message: "down" } }),
    });
    renderApp();
    expect(await screen.findByRole("alertdialog", { name: "Database unreachable" })).toBeInTheDocument();
    expect(screen.queryByText("clauses")).toBeNull();
  });
});
