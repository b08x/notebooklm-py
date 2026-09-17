"""Audio Overview assessment orchestration.

Owns the full pipeline behind the TUI's "Assess Audio Overview" action:
resolving the artifact, transcribing it, ingesting the transcript as a source
under the notebook, running the NLP preprocessing pipeline, and scoring the
result with an LLM. :mod:`notebooklm.tui.views.assessment_view` and
:mod:`notebooklm.tui.keypress` call only into this module and read
``state.assessment_state`` — they hold no direct imports of
``PreprocessingPipeline`` or ``generate_assessment``.

This module is transport-neutral — no ``click`` / ``rich`` / ``tui`` imports
(enforced by ``tests/_guardrails/test_app_boundary.py``, same boundary rule as
every other ``_app`` module). It is allowed to depend on
``notebooklm._preprocessing`` (a standalone domain library, not a client-runtime
internal — see that guardrail's docstring for the carve-out).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import dspy

from .._preprocessing.fact_check import FactCheckAdapter
from .._preprocessing.ingestion import IngestionService, resolve_notebook_context
from .._preprocessing.pipeline import PreprocessingPipeline
from .._preprocessing.transcription import (
    AssemblyAIAdapter,
    DeepgramAdapter,
    SpeechmaticsAdapter,
    TranscribeCppAdapter,
    TranscriptionAdapter,
    TranscriptionService,
)
from .artifacts import get_artifact, get_artifact_prompt

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from ..client import NotebookLMClient

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# DSPy scoring (pre-existing; unchanged in behavior)
# ---------------------------------------------------------------------------


#: Default chat-completion model for assessment scoring/fact-check/clause-search
#: answering: a low-cost OpenRouter model (picked to stay well under $0.10/request
#: on input cost). Embeddings are a separate concern — those stay local via Ollama
#: (see ``NOTEBOOKLM_ASSESSMENT_EMBED_PROVIDER``/``_EMBED_MODEL`` below); this repo's
#: local Ollama host is embeddings-only and has no chat models pulled.
DEFAULT_MODEL_PROVIDER = "openrouter"
DEFAULT_MODEL = "deepseek/deepseek-v4-flash-0731"


def setup_dspy_router():
    """
    Sets up DSPy model and embedding routing based on environment variables.
    Routes to either local (Ollama) or a provider model (default: OpenRouter).
    Requires ``OPENROUTER_API_KEY`` in the environment when using the default
    provider (litellm reads it directly; no other wiring needed).
    """
    model_provider = os.getenv(
        "NOTEBOOKLM_ASSESSMENT_MODEL_PROVIDER", DEFAULT_MODEL_PROVIDER
    ).lower()
    model_name = os.getenv("NOTEBOOKLM_ASSESSMENT_MODEL", DEFAULT_MODEL)

    if model_provider == "ollama":
        lm = dspy.LM(f"ollama_chat/{model_name}")
    else:
        api_key = os.environ.get("OPENROUTER_API_KEY") if model_provider == "openrouter" else None
        kwargs = {"api_key": api_key} if api_key else {}
        lm = dspy.LM(f"{model_provider}/{model_name}", **kwargs)

    embed_provider = os.getenv("NOTEBOOKLM_ASSESSMENT_EMBED_PROVIDER", "ollama").lower()
    embed_model = os.getenv("NOTEBOOKLM_ASSESSMENT_EMBED_MODEL", "nomic-embed-text")

    if embed_provider == "ollama":
        embedder = dspy.Embedder(f"ollama/{embed_model}")
    else:
        embedder = dspy.Embedder(f"{embed_provider}/{embed_model}")

    dspy.settings.configure(lm=lm)
    return lm, embedder


class AudioOverviewAssessmentSignature(dspy.Signature):
    """Assess an audio overview generation based on system instructions and contextualized source chunks."""

    system_instructions = dspy.InputField(
        desc="The original system instructions for generating the audio overview."
    )
    audio_metadata = dspy.InputField(desc="Metadata of the generated audio.")
    source_chunks = dspy.InputField(
        desc="Contextualized source chunks used for the audio generation."
    )

    score = dspy.OutputField(
        desc="Suggested score out of 10 for how well it followed the instructions."
    )
    feedback = dspy.OutputField(desc="Feedback on what went well and what could be improved.")


class AudioOverviewAssessor(dspy.Module):
    def __init__(self):
        super().__init__()
        self.assess = dspy.ChainOfThought(AudioOverviewAssessmentSignature)

    def forward(self, system_instructions: str, audio_metadata: str, source_chunks: list[str]):
        chunks_text = "\n\n".join(source_chunks)
        return self.assess(
            system_instructions=system_instructions,
            audio_metadata=audio_metadata,
            source_chunks=chunks_text,
        )


def generate_assessment(
    system_instructions: str, audio_metadata: str, chunks: list[str]
) -> dict[str, str]:
    """
    Run the asynchronous LLM call (via DSPy) to get suggested score and feedback.
    """
    lm, embedder = setup_dspy_router()
    assessor = AudioOverviewAssessor()

    try:
        prediction = assessor(
            system_instructions=system_instructions,
            audio_metadata=audio_metadata,
            source_chunks=chunks,
        )
        return {"score": prediction.score, "feedback": prediction.feedback}
    except Exception as e:
        return {"score": "Error", "feedback": f"Failed to generate assessment: {str(e)}"}


# ---------------------------------------------------------------------------
# Full pipeline orchestration
# ---------------------------------------------------------------------------


#: Env var picking the transcription adapter ``run_full_assessment`` uses.
#: `TranscribeCppAdapter`'s local-diarization path is still in progress
#: upstream; this only makes the choice configurable, not that path complete.
TRANSCRIBE_PROVIDER_ENV = "NOTEBOOKLM_ASSESSMENT_TRANSCRIBE_PROVIDER"

_TRANSCRIPTION_ADAPTERS: dict[str, type[TranscriptionAdapter]] = {
    "deepgram": DeepgramAdapter,
    "assemblyai": AssemblyAIAdapter,
    "speechmatics": SpeechmaticsAdapter,
    "transcribe_cpp": TranscribeCppAdapter,
}


def _build_transcription_adapter() -> TranscriptionAdapter:
    provider = os.environ.get(TRANSCRIBE_PROVIDER_ENV, "deepgram").lower()

    # Auto-fallback to local transcribe_cpp if Deepgram is requested but no key is provided
    if provider == "deepgram" and not os.environ.get("DEEPGRAM_API_KEY"):
        provider = "transcribe_cpp"

    adapter_cls = _TRANSCRIPTION_ADAPTERS.get(provider)
    if adapter_cls is None:
        raise ValueError(
            f"Unknown {TRANSCRIBE_PROVIDER_ENV}={provider!r}; "
            f"expected one of {sorted(_TRANSCRIPTION_ADAPTERS)}"
        )
    return adapter_cls()


@dataclass
class AssessmentChunk:
    """One structured, renderable chunk plus its persisted-clause hookup."""

    text: str
    clause_external_id: str
    topic_id: int = -1
    entities: list[tuple[str, str]] = field(default_factory=list)
    #: ``None`` = not yet fact-checked. Set by :func:`run_fact_check_for_chunk`.
    fact_check_passed: bool | None = None
    fact_check_citations: str | None = None

    @property
    def formatted(self) -> str:
        """Flattened text representation, e.g. for LLM scoring input."""
        ent_str = ", ".join(f"{label} ({kind})" for label, kind in self.entities) or "None"
        return f"{self.text}\n\n--- Metadata ---\nTopic ID: {self.topic_id}\nEntities: {ent_str}"


@dataclass
class AssessmentResult:
    """Everything the Assessment view needs to render + drive further actions."""

    system_instructions: str
    audio_metadata: str
    transcript: str
    chunks: list[AssessmentChunk]
    sfl_metrics: dict[str, Any] | None = None


async def run_full_assessment(
    client: NotebookLMClient,
    session: AsyncSession,
    notebook_id: str,
    artifact_id: str,
    *,
    context_override: str | None = None,
    progress_callback=None,
    state_callback=None,
) -> AssessmentResult:
    # Initialize the DSPy router for this parent thread,
    # so background tasks can inherit the LM via dspy.context.
    setup_dspy_router()

    """Resolve, transcribe, ingest, and preprocess a notebook's audio overview.

    Downloads the artifact via the existing ``client.artifacts.download_audio``
    path (the same download the CLI's ``download audio`` command drives),
    transcribes it with a configurable :class:`TranscriptionAdapter`, ingests the
    transcript as a source under ``notebook_id`` (keyed by ``artifact_id``,
    alongside the notebook's regular sources' clauses), and runs it through
    :class:`PreprocessingPipeline`.
    Runs SFL analysis and fact checking for all chunks.
    """
    await get_artifact(client, notebook_id, artifact_id)
    system_instructions = await get_artifact_prompt(client, notebook_id, artifact_id) or ""

    from sqlalchemy import select

    from ..db.models import LocalAsset

    result = await session.execute(select(LocalAsset).where(LocalAsset.asset_id == artifact_id))
    local_asset = result.scalar_one_or_none()

    # Determine where artifacts should live (or already live)
    if local_asset and os.path.exists(local_asset.local_path):
        artifacts_dir = os.path.dirname(local_asset.local_path)
    else:
        artifacts_dir = os.path.expanduser("~/NotebookLM/artifacts")

    os.makedirs(artifacts_dir, exist_ok=True)
    transcript_path = os.path.join(artifacts_dir, f"{artifact_id}_transcript.txt")
    json_path = os.path.join(artifacts_dir, f"{artifact_id}_diarization.json")

    # If already transcribed, pull from cache
    if os.path.exists(transcript_path):
        if progress_callback:
            progress_callback("Loading cached transcription...")
        with open(transcript_path, encoding="utf-8") as f:
            transcript = f.read()

        diarization = None
        if os.path.exists(json_path):
            with open(json_path, encoding="utf-8") as f:
                diarization = json.load(f)

        provider = "cached"
    else:
        # Otherwise, run the transcription pipeline
        if progress_callback:
            progress_callback("Transcribing audio overview (may take a minute)...")
        if local_asset and os.path.exists(local_asset.local_path):
            audio_path = local_asset.local_path
            adapter = _build_transcription_adapter()
            transcription: dict[str, Any] = await asyncio.to_thread(
                TranscriptionService(adapter).transcribe_audio, audio_path
            )
        else:
            if progress_callback:
                progress_callback("Downloading audio overview from NotebookLM...")
            with tempfile.TemporaryDirectory() as tmpdir:
                audio_path = os.path.join(tmpdir, f"{artifact_id}.audio")
                await client.artifacts.download_audio(notebook_id, audio_path, artifact_id)

                if progress_callback:
                    progress_callback("Transcribing downloaded audio...")
                adapter = _build_transcription_adapter()
                transcription = await asyncio.to_thread(
                    TranscriptionService(adapter).transcribe_audio, audio_path
                )

        transcript = transcription.get("text", "")
        diarization = transcription.get("diarization")
        provider = transcription.get("provider")

        # Persist the transcript and JSON to disk for future cached runs
        with open(transcript_path, "w", encoding="utf-8") as f:
            f.write(transcript)

        if diarization:
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(diarization, f, indent=2, default=str)

    audio_metadata = json.dumps(
        {
            "provider": provider,
            "diarization_saved_to": json_path if diarization else None,
            "transcript_path": transcript_path,
        },
        default=str,
    )

    if progress_callback:
        progress_callback("Running SFL transcript analysis...")
    from .._preprocessing.sfl_engine import analyze_transcript
    sfl_metrics = analyze_transcript(transcript, diarization=diarization)

    if progress_callback:
        progress_callback("Chunking and extracting entities...")
    enable_pii = os.environ.get("NOTEBOOKLM_ENABLE_PII_FILTER", "false").lower() == "true"
    pipeline = PreprocessingPipeline(enable_pii_filter=enable_pii)
    processed_chunks = pipeline.process(transcript)

    if progress_callback:
        progress_callback("Resolving notebook context...")
    context = (
        context_override
        if context_override is not None
        else await resolve_notebook_context(client, notebook_id)
    )

    if progress_callback:
        progress_callback(f"Embedding and ingesting {len(processed_chunks)} chunks...")
    ingestion = IngestionService(client)
    await ingestion.ingest_chunks(
        session,
        document_id=artifact_id,
        chunks=[c.text for c in processed_chunks],
        context=context,
    )

    assessment_chunks = [
        AssessmentChunk(
            text=c.text,
            clause_external_id=f"{artifact_id}:{i}",
            topic_id=c.topic_id,
            entities=c.entities,
        )
        for i, c in enumerate(processed_chunks)
    ]

    # Run fact checking concurrently but bounded to prevent database connection exhaustion
    fact_check_tasks = [
        run_fact_check_for_chunk(c.clause_external_id, c.text) for c in assessment_chunks
    ]
    if fact_check_tasks:
        sem = asyncio.Semaphore(5)

        def _extract_speaker(chunk_text: str) -> str:
            prefix = chunk_text[:40].strip()

            if provider == "assemblyai" and isinstance(diarization, list):
                for utt in diarization:
                    if prefix in utt.get("text", ""):
                        return f"[Speaker {utt.get('speaker', '?')}] "
            elif provider == "deepgram" and isinstance(diarization, dict):
                try:
                    words = diarization["results"]["channels"][0]["alternatives"][0]["words"]
                    prefix_word = prefix.split()[0].strip('.,?!')
                    for w in words:
                        if w.get("punctuated_word", "").strip('.,?!') == prefix_word:
                            return f"[Speaker {w.get('speaker', '?')}] "
                except Exception:
                    pass
            elif provider == "speechmatics" and isinstance(diarization, dict):
                try:
                    results = diarization.get("results", [])
                    prefix_word = prefix.split()[0].strip('.,?!')
                    for r in results:
                        if r.get("type") == "word" and r.get("alternatives"):
                            content = r["alternatives"][0].get("content", "").strip('.,?!')
                            if content == prefix_word and r["alternatives"][0].get("speaker"):
                                return f"[{r['alternatives'][0]['speaker']}] "
                except Exception:
                    pass

            return ""

        async def _run_with_sem(task, chunk_text):
            speaker_prefix = _extract_speaker(chunk_text)
            display_text = f"{speaker_prefix}{chunk_text}"

            if state_callback:
                state_callback("current_chunk_text", display_text[:200] + "...")
            async with sem:
                res = await task

            if state_callback:
                # Emit rich dict for UI to render
                state_callback("ticker_stream_append", {
                    "passed": res.passed,
                    "text": display_text.strip(),
                    "citations": res.citations.replace('\n', ' ').strip() if res.citations else ""
                })

            return res

        wrapped_tasks = [_run_with_sem(t, c.text) for t, c in zip(fact_check_tasks, assessment_chunks)]

        results = []
        passed_count = 0
        failed_count = 0
        total_tasks = len(wrapped_tasks)
        for completed, coro in enumerate(asyncio.as_completed(wrapped_tasks), start=1):
            res = await coro
            results.append(res)

            if res.passed:
                passed_count += 1
            else:
                failed_count += 1

            if state_callback:
                state_callback("metrics", {
                    "completed": completed,
                    "total": total_tasks,
                    "passed": passed_count,
                    "failed": failed_count,
                })

            if progress_callback:
                progress_callback(f"Fact-checking chunk {completed}/{total_tasks}...")

        # Re-map results to chunks
        res_map = {res.clause_external_id: res for res in results}
        for chunk in assessment_chunks:
            res = res_map.get(chunk.clause_external_id)
            if res:
                chunk.fact_check_passed = res.passed
                chunk.fact_check_citations = res.citations
    return AssessmentResult(
        system_instructions=system_instructions,
        audio_metadata=audio_metadata,
        transcript=transcript,
        chunks=assessment_chunks,
        sfl_metrics=sfl_metrics,
    )


@dataclass
class ScoringResult:
    """Outcome of :func:`run_assessment_scoring`: the chunks scored, plus the verdict."""

    chunks: list[Any]
    score: str
    feedback: str


def generate_assessment_report(
    artifact_id: str, assessment_state: dict, scoring_result: ScoringResult, output_dir: str
) -> str:
    """Generates a detailed Markdown report containing SFL metrics, LLM scoring, and fact-check results."""
    import os
    from datetime import datetime

    os.makedirs(output_dir, exist_ok=True)
    report_path = os.path.join(output_dir, f"fact_check_report_{artifact_id}.md")

    lines = [
        "# Fact-Check and Assessment Report",
        f"**Artifact ID**: `{artifact_id}`",
        f"**Date**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "## 1. Score & Feedback (DSPy Evaluator)",
        f"**Score**: {scoring_result.score}/10",
        "",
        f"**Feedback**: {scoring_result.feedback}",
        "",
        "## 2. Systemic Functional Linguistics (SFL) Analysis",
    ]

    metrics = assessment_state.get("sfl_metrics") or {}
    lines.append(f"- **Total Clauses**: {metrics.get('total_clauses', 'N/A')}")
    lines.append(f"- **Speaker Shifts**: {metrics.get('speaker_shifts', 'N/A')}")
    lines.append(f"- **Pragmatic Intentions**: {metrics.get('pragmatic_intentions', 'N/A')}")
    lines.append(f"- **Semiotics Analyzed**: {metrics.get('semiotics', 'N/A')}")
    lines.append("")

    lines.append("## 3. Fact-Check Citations and Warnings")

    chunks = assessment_state.get("chunks", [])
    failed_chunks = [c for c in chunks if getattr(c, "fact_check_passed", None) is False]

    if failed_chunks:
        lines.append("### ⚠️ Data Quality Warnings (Failed Claims)")
        for chunk in failed_chunks:
            lines.append(f"> **Chunk**: {chunk.text}")
            lines.append(
                f"> **Citations/Verification**: {getattr(chunk, 'fact_check_citations', 'No citations found.')}"
            )
            lines.append("")
    else:
        lines.append("✅ *All verifiable claims passed or no explicit failures detected.*")
        lines.append("")

    lines.append("### Full Contextual Chunk Verification")
    for idx, chunk in enumerate(chunks):
        passed = getattr(chunk, "fact_check_passed", None)
        status = "✅ PASS" if passed is True else "❌ FAIL" if passed is False else "❓ UNVERIFIED"
        lines.append(f"#### Chunk {idx + 1} ({status})")
        lines.append(f"{chunk.text}")
        citations = getattr(chunk, "fact_check_citations", None)
        if citations:
            lines.append(f"\n*Citations*: {citations}")
        lines.append("")

    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    return report_path


def run_assessment_scoring(
    chunks: list[Any] | None,
    system_instructions: str,
    audio_metadata: str,
    raw_text_fallback: str | None = None,
) -> ScoringResult:
    """Score ``chunks`` via :func:`generate_assessment`, preprocessing first if empty.

    The TUI's Assessment-view Enter-key action calls this rather than importing
    ``PreprocessingPipeline``/``generate_assessment`` directly. When ``chunks`` is
    empty (the view was entered directly with no real notebook context, e.g. the
    bare ``A`` keypress), this runs :class:`PreprocessingPipeline` over
    ``raw_text_fallback`` (defaulting to the historical sample text) first — the
    real-notebook-data path (populated by :func:`run_full_assessment`) never hits
    this branch since its chunks list is already populated.
    """
    if not chunks:
        text = raw_text_fallback or "Sample text for NotebookLM to assess. This contains a PII."
        enable_pii = os.environ.get("NOTEBOOKLM_ENABLE_PII_FILTER", "false").lower() == "true"
        pipeline = PreprocessingPipeline(enable_pii_filter=enable_pii)
        chunks = pipeline.process(text)

    chunk_texts: list[str] = []
    for c in chunks:
        formatted = getattr(c, "formatted", None)
        chunk_texts.append(formatted if isinstance(formatted, str) else str(c))
    if not chunk_texts:
        chunk_texts = ["No Source Chunks Available."]

    scored = generate_assessment(system_instructions, audio_metadata, chunk_texts)
    return ScoringResult(chunks=chunks, score=scored["score"], feedback=scored["feedback"])


@dataclass
class FactCheckResult:
    """Outcome of a single-chunk fact-check, plus SIFT-framework availability."""

    clause_external_id: str
    passed: bool
    framework_available: bool
    citations: str


async def run_fact_check_for_chunk(
    clause_external_id: str,
    text: str,
) -> FactCheckResult:
    """Run :class:`FactCheckAdapter` on one chunk and persist the verdict.

    Persists onto the matching ``Clause.fact_check_passed`` row (keyed by
    ``clause_external_id``). ``framework_available`` distinguishes a real
    verdict from the adapter's always-pass fallback when the external SIFT
    framework isn't installed, so the UI never presents the fallback as a real
    fact-check result.
    """
    import dspy
    from sqlalchemy import update

    from ..db.models import Clause
    from ..db.session import async_session_maker

    checker = FactCheckAdapter()
    framework_available = checker.framework_available

    # Grab the LM from the main thread's context before spanning to background thread
    lm = dspy.settings.lm

    def _run_with_context():
        with dspy.context(lm=lm):
            return checker.check(text)

    passed, citations = await asyncio.to_thread(_run_with_context)

    async with async_session_maker() as session:
        await session.execute(
            update(Clause)
            .where(Clause.external_id == clause_external_id)
            .values(fact_check_passed=passed)
        )
        await session.commit()

    return FactCheckResult(
        clause_external_id=clause_external_id,
        passed=passed,
        framework_available=framework_available,
        citations=citations,
    )
