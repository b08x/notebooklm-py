import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { mockFetch, renderWithClient, row, SseBody, Status, sse } from "@/test/utils";
import { store } from "@/state/store";
import { AskDrawer } from "./AskDrawer";

const HITS = [{ ...row({ external_id: "a:1:0" }), kw_rank: 1, vec_rank: 1, score: 0.03, distance: 0.1 }];

function open(selected: string[] = []) {
  act(() => store.set({ askOpen: true, selected, submittedQuery: "why do kernels panic" }));
}

describe("AskDrawer (facts 27-30, 60-61)", () => {
  it("NotebookLM mode shows a progress state, then the answer with citations", async () => {
    let release: (v: unknown) => void = () => {};
    const gate = new Promise((r) => (release = r));
    const calls = mockFetch({
      "POST /v1/corpus/answer": async () => {
        await gate;
        return { mode: "notebooklm", answer: "Cgroups [C1].", labels: { C1: "a:1:0" }, citations: { C1: "a:1:0" }, hits: HITS };
      },
    });
    renderWithClient(<AskDrawer />);
    open(["a:1:0"]);
    fireEvent.click(screen.getByRole("radio", { name: "NotebookLM" }));
    expect(screen.getByLabelText("Question")).toHaveValue("why do kernels panic");
    fireEvent.click(screen.getByRole("button", { name: /Ask/ }));
    expect(await screen.findByRole("status")).toHaveTextContent("NotebookLM is answering");
    release(null);
    expect(await screen.findByTestId("answer")).toHaveTextContent("Cgroups C1.");
    expect(calls.find((c) => c.path === "/v1/corpus/answer")?.body).toMatchObject({ mode: "notebooklm", ids: ["a:1:0"] });
    fireEvent.click(screen.getByRole("button", { name: "C1" }));
    expect(store.get().detailId).toBe("a:1:0");
  });

  it("a picked litellm model streams token by token", async () => {
    const calls = mockFetch({
      "POST /v1/corpus/answer": new SseBody(
        sse([
          { type: "hits", hits: HITS, labels: { C1: "a:1:0" } },
          { type: "token", text: "Spa" },
          { type: "token", text: "Cy [C1]" },
          { type: "done", answer: "SpaCy [C1]", citations: { C1: "a:1:0" } },
        ]),
      ),
    });
    renderWithClient(<AskDrawer />);
    open();
    fireEvent.click(screen.getByRole("radio", { name: "Model…" }));
    fireEvent.change(screen.getByLabelText("Model"), { target: { value: "openrouter/x/y" } });
    fireEvent.click(screen.getByRole("button", { name: /Ask/ }));
    await waitFor(() => expect(screen.getByTestId("answer")).toHaveTextContent("SpaCy C1"));
    expect(calls[0].body).toMatchObject({ mode: "model", model: "openrouter/x/y" });
    expect(localStorage.getItem("ce-model")).toBe("openrouter/x/y");
    expect(screen.getByText("Grounding chunks")).toBeInTheDocument();
  });

  it("Deep mode is labelled experimental and shows a clear sandbox error", async () => {
    mockFetch({
      "POST /v1/corpus/answer": new Status(409, { error: { category: "deep_mode_unavailable", message: "needs the Deno sandbox" } }),
    });
    renderWithClient(<AskDrawer />);
    open();
    const deep = screen.getByRole("radio", { name: /Deep/ });
    expect(deep).toHaveTextContent("experimental");
    fireEvent.click(deep);
    fireEvent.click(screen.getByRole("button", { name: /Ask/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Deep mode unavailable: needs the Deno sandbox");
  });

  it("the corpus agent result shows its mode", async () => {
    mockFetch({
      "POST /v1/corpus/answer": { mode: "corpus_agent", answer: "Merged [C1].", labels: { C1: "a:1:0" }, citations: {}, hits: HITS },
    });
    renderWithClient(<AskDrawer />);
    open();
    fireEvent.click(screen.getByRole("radio", { name: "Corpus agent" }));
    fireEvent.click(screen.getByRole("button", { name: /Ask/ }));
    expect(await screen.findByText("corpus agent")).toBeInTheDocument();
  });
});
