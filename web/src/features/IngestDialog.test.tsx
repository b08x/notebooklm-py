import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { mockFetch, renderWithClient, SseBody, sse } from "@/test/utils";
import { store } from "@/state/store";
import { IngestDialog } from "./IngestDialog";

const PROVIDERS = {
  providers: [
    { id: "speechmatics", label: "Speechmatics", env_var: "SPEECHMATICS_API_KEY", key_present: false },
    { id: "assemblyai", label: "AssemblyAI", env_var: "ASSEMBLYAI_API_KEY", key_present: false },
    { id: "deepgram", label: "Deepgram", env_var: "DEEPGRAM_API_KEY", key_present: true },
    { id: "transcribe_cpp", label: "Local transcribe_cpp", env_var: "NOTEBOOKLM_TRANSCRIBE_CPP_MODEL", key_present: false },
  ],
  defaults: { provider: "deepgram", diarize: true, language: "auto" },
};

const ARTIFACTS = {
  items: [
    { id: "aud", title: "Deep dive", kind: "audio", media: "audio", ingestible: true, reason: null, ingested: false },
    { id: "rep", title: "Briefing", kind: "report", media: "text", ingestible: true, reason: null, ingested: true },
    { id: "inf", title: "Poster", kind: "infographic", media: "image", ingestible: false, reason: "image-only, not ingestible yet", ingested: false },
  ],
};

function setup() {
  const calls = mockFetch({
    "GET /v1/corpus/notebooks": { items: [{ id: "nb", title: "Notebook", chunks: 3, documents: 1 }] },
    "GET /v1/corpus/artifacts": ARTIFACTS,
    "GET /v1/corpus/transcription/providers": PROVIDERS,
    "POST /v1/corpus/artifacts/aud/ingest": { id: "job1", kind: "ingest", label: "x", status: "queued", message: "", done: 0, total: 0, result: null, error: null, document_ids: ["aud"], last_seq: 0 },
    "GET /v1/corpus/jobs/job1/events": () =>
      new SseBody(
        sse([
          { seq: 1, type: "progress", message: "Transcribing with speechmatics" },
          { seq: 2, type: "finished", status: "done", result: { status: "ingested", n_children: 12 }, error: null },
        ]),
      ),
  });
  renderWithClient(<IngestDialog />);
  act(() => store.set({ ingestOpen: true }));
  return calls;
}

describe("IngestDialog (facts 51, 54, 57)", () => {
  it("lists artifacts; image kinds are disabled with a reason", async () => {
    setup();
    const poster = await screen.findByRole("option", { name: /Poster/ });
    expect(poster).toBeDisabled();
    expect(poster).toHaveTextContent("image-only, not ingestible yet");
    expect(screen.getByRole("option", { name: /Briefing/ })).toHaveTextContent("ingested");
  });

  it("audio shows the provider panel; a provider without its env var reads key missing", async () => {
    setup();
    fireEvent.click(await screen.findByRole("option", { name: /Deep dive/ }));
    const panel = await screen.findByTestId("transcription-panel");
    await waitFor(() => expect(screen.getByTestId("key-status")).toHaveTextContent("key found · DEEPGRAM_API_KEY"));
    fireEvent.click(screen.getByRole("radio", { name: "Speechmatics" }));
    expect(screen.getByTestId("key-status")).toHaveTextContent("key missing · SPEECHMATICS_API_KEY");
    expect(panel).toHaveTextContent("Diarize");
    expect(screen.getByRole("switch", { name: "Diarize" })).toBeChecked();
    expect(screen.getByRole("combobox", { name: "Language" })).toHaveTextContent("Auto-detect");
    expect(screen.getByRole("button", { name: "Transcribe" })).toBeEnabled();
  });

  it("Transcribe posts the chosen options and follows the job", async () => {
    const calls = setup();
    fireEvent.click(await screen.findByRole("option", { name: /Deep dive/ }));
    await screen.findByTestId("transcription-panel");
    fireEvent.click(screen.getByRole("radio", { name: "Speechmatics" }));
    await userEvent.click(screen.getByRole("switch", { name: "Diarize" }));
    fireEvent.click(screen.getByRole("button", { name: "Transcribe" }));
    await waitFor(() => expect(calls.find((c) => c.path === "/v1/corpus/artifacts/aud/ingest")).toBeTruthy());
    expect(calls.find((c) => c.path === "/v1/corpus/artifacts/aud/ingest")?.body).toEqual({
      notebook_id: "nb",
      provider: "speechmatics",
      diarize: false,
      language: "auto",
      force: false,
    });
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Ingested 12 chunks"));
  });

  it("text artifacts skip transcription and just ingest", async () => {
    setup();
    fireEvent.click(await screen.findByRole("option", { name: /Briefing/ }));
    expect(screen.queryByTestId("transcription-panel")).toBeNull();
    expect(screen.getByRole("button", { name: "Ingest" })).toBeEnabled();
  });
});
