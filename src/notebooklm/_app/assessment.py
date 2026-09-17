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
DEFAULT_MODEL = "z-ai/glm-5.3-flash"


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
        lm = dspy.LM(f"{model_provider}/{model_name}")

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


async def run_full_assessment(
    client: NotebookLMClient,
    session: AsyncSession,
    notebook_id: str,
    artifact_id: str,
    *,
    context_override: str | None = None,
) -> AssessmentResult:
    """Resolve, transcribe, ingest, and preprocess a notebook's audio overview.

    Downloads the artifact via the existing ``client.artifacts.download_audio``
    path (the same download the CLI's ``download audio`` command drives),
    transcribes it with a configurable :class:`TranscriptionAdapter`, ingests the
    transcript as a source under ``notebook_id`` (keyed by ``artifact_id``,
    alongside the notebook's regular sources' clauses), and runs it through
    :class:`PreprocessingPipeline`. Fact-checking is not run here — chunks start
    unchecked; see :func:`run_fact_check_for_chunk`.

    Chunk embeddings are contextualized with the notebook's own AI-generated
    summary (free, via :func:`resolve_notebook_context`) unless
    ``context_override`` is given (a user-edited summary, or ``""`` for no
    context) — this avoids a separate paid LLM call just to generate that
    per-chunk context.
    """
    await get_artifact(client, notebook_id, artifact_id)
    system_instructions = await get_artifact_prompt(client, notebook_id, artifact_id) or ""

    with tempfile.TemporaryDirectory() as tmpdir:
        audio_path = os.path.join(tmpdir, f"{artifact_id}.audio")
        await client.artifacts.download_audio(notebook_id, audio_path, artifact_id)

        adapter = _build_transcription_adapter()
        transcription: dict[str, Any] = await asyncio.to_thread(
            TranscriptionService(adapter).transcribe_audio, audio_path
        )

    transcript = transcription.get("text", "")
    audio_metadata = json.dumps(
        {
            "provider": transcription.get("provider"),
            "diarization": transcription.get("diarization"),
        },
        default=str,
    )

    pipeline = PreprocessingPipeline()
    processed_chunks = pipeline.process(transcript)

    context = (
        context_override
        if context_override is not None
        else await resolve_notebook_context(client, notebook_id)
    )

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

    return AssessmentResult(
        system_instructions=system_instructions,
        audio_metadata=audio_metadata,
        transcript=transcript,
        chunks=assessment_chunks,
    )


@dataclass
class ScoringResult:
    """Outcome of :func:`run_assessment_scoring`: the chunks scored, plus the verdict."""

    chunks: list[Any]
    score: str
    feedback: str


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
        pipeline = PreprocessingPipeline()
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


async def run_fact_check_for_chunk(
    session: AsyncSession,
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
    from sqlalchemy import update

    from ..db.models import Clause

    checker = FactCheckAdapter()
    framework_available = checker.framework_available
    passed = await asyncio.to_thread(checker.check, text)

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
    )
