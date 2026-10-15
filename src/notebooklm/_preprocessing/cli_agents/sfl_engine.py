"""SFL engine whose interpersonal pass runs on an LLM CLI coding agent.

Pass 1 (ideational: participants, processes, circumstances) is the same
deterministic spaCy analysis :class:`~notebooklm._preprocessing.sfl_engine.SFLEngine`
uses. Pass 2 (interpersonal: mood, modality, tenor; textual: theme, rheme,
cohesive markers) is one agent invocation, normally of the CLI's named
``sfl-annotator`` agent, using the ``sfl-metafunction-annotation`` taxonomy.

:meth:`AgentSFLEngine.forward_batch` sends every clause of a parent chunk in a
single prompt (split into ``max_batch``-sized sub-batches), because spawning an
agent process per clause costs seconds each. Recovery is layered:

1. A failed or incomplete batch reruns the missing clauses one prompt each
   (``per_clause_retry``).
2. When the agent itself is unusable (missing binary, timeout, non-zero exit,
   unparseable output) and ``fallback`` is on, the clause goes to the DSPy
   ``SFLEngine``. A missing binary skips step 1: retrying cannot help.

Output matches ``SFLEngine.forward``: ``{"ideational": ..., "interpersonal": ...}``
plus ``"backend"`` naming what produced the interpersonal analysis
(``"agent:<name>"`` or ``"dspy-fallback"``), which ``to_sfl`` stores under ``raw``.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Sequence
from typing import Any

from .adapter import AgentError, AgentNotFoundError, AgentParseError, CLIAgentAdapter

logger = logging.getLogger(__name__)

INTERPERSONAL_KEYS = ("mood", "modality", "tenor")
TEXTUAL_KEYS = ("theme", "rheme", "cohesive_markers")
ANNOTATION_KEYS = INTERPERSONAL_KEYS + TEXTUAL_KEYS
DEFAULT_MAX_BATCH = 40
#: Named agent each CLI loads for annotation (see ``sfl-metafunction-annotation`` skill).
DEFAULT_AGENT_PROFILE = "sfl-annotator"

# Allowed values from the ``sfl-metafunction-annotation`` skill.
MOOD_VALUES = (
    "declarative",
    "interrogative_polar",
    "interrogative_wh",
    "imperative",
    "exclamative",
    "fragment",
)
MODALITY_VALUES = ("low", "median", "high", "neutral")
TENOR_VALUES = ("formal", "academic", "neutral", "casual", "slang")

ANNOTATION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "annotations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer"},
                    "mood": {"type": "string", "enum": list(MOOD_VALUES)},
                    "modality": {"type": "string", "enum": list(MODALITY_VALUES)},
                    "tenor": {"type": "string", "enum": list(TENOR_VALUES)},
                    "theme": {"type": "string"},
                    "rheme": {"type": "string"},
                    "cohesive_markers": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["index", *ANNOTATION_KEYS],
            },
        }
    },
    "required": ["annotations"],
}

# Self-contained: a CLI without the ``sfl-annotator`` agent still gets the full
# taxonomy, and with the agent loaded this restates its skill for a batch.
_INSTRUCTIONS = f"""\
Annotate each clause below with Systemic Functional Linguistics (SFL) Interpersonal
and Textual metafunction labels, using its deterministic pass1_analysis
(participants, processes, circumstances) as grounding.
Do not use tools, read files, or edit anything. Answer from the text below only.

For each clause return exactly these keys:
- mood: mood of the first independent clause; one of {", ".join(MOOD_VALUES)}
  (fragment only when there is no finite clause)
- modality: one of {", ".join(MODALITY_VALUES)}
  (low: may/might/could/possibly; median: will/would/should/probably;
  high: must/have to/certainly; neutral: no modal operator or adjunct)
- tenor: one of {", ".join(TENOR_VALUES)}
- theme: verbatim substring that is the point of departure, up to and including the
  first experiential element (participant or circumstance); preceding textual or
  interpersonal elements ("so", "well") belong to the theme
- rheme: the verbatim remainder; theme + whitespace + rheme must equal the utterance
- cohesive_markers: list of verbatim discourse markers / conjunctions / reference
  items linking to prior discourse; [] if none

This is a batch: the usual single-object output is replaced by one array.
Respond with JSON only, no prose and no code fences, matching exactly:
{{"annotations": [{{"index": <clause index>, "mood": "...", "modality": "...", "tenor": "...", "theme": "...", "rheme": "...", "cohesive_markers": []}}]}}
Return exactly one annotation per clause index listed.

Clauses:
"""


def build_prompt(items: Sequence[tuple[int, str, dict[str, Any]]]) -> str:
    """Prompt for ``(index, utterance, pass1)`` items."""
    clauses = [
        {"index": index, "utterance": text, "pass1_analysis": pass1} for index, text, pass1 in items
    ]
    return _INSTRUCTIONS + json.dumps(clauses, ensure_ascii=False, indent=1)


def parse_annotations(payload: Any, indices: Sequence[int]) -> dict[int, dict[str, Any]]:
    """Map clause index to interpersonal dict from an agent payload.

    Accepts ``{"annotations": [...]}``, a bare list, or (for one clause) a single
    annotation object. Entries without a usable ``index`` are matched by position.
    Raises :class:`ValueError` when the payload holds no annotations.
    """
    if isinstance(payload, dict) and isinstance(payload.get("annotations"), list):
        entries: list[Any] = payload["annotations"]
    elif isinstance(payload, list):
        entries = payload
    elif isinstance(payload, dict) and any(k in payload for k in ANNOTATION_KEYS):
        entries = [payload]
    else:
        raise ValueError(f"no annotations in payload of type {type(payload).__name__}")

    wanted = set(indices)
    found: dict[int, dict[str, Any]] = {}
    for position, entry in enumerate(entries):
        if not isinstance(entry, dict):
            continue
        raw_index = entry.get("index")
        index: int | None
        try:
            index = int(raw_index) if raw_index is not None else None
        except (TypeError, ValueError):
            index = None
        if index not in wanted:
            index = indices[position] if position < len(indices) else None
        if index is None or index in found:
            continue
        found[index] = {k: v for k, v in entry.items() if k != "index"}
    if not found:
        raise ValueError("payload annotations matched no clause")
    return found


def _default_pass1(utterance: str) -> dict[str, Any]:
    from ..sfl_engine import ideational_analysis

    return ideational_analysis(utterance)


def _default_fallback() -> Any:
    from ..sfl_engine import SFLEngine

    return SFLEngine()


class AgentSFLEngine:
    """Hybrid spaCy pass-1 + CLI agent pass-2 SFL engine (see module docstring)."""

    def __init__(
        self,
        adapter: CLIAgentAdapter,
        *,
        batch: bool = True,
        max_batch: int = DEFAULT_MAX_BATCH,
        per_clause_retry: bool = True,
        fallback: bool = True,
        fallback_factory: Callable[[], Any] = _default_fallback,
        pass1: Callable[[str], dict[str, Any]] = _default_pass1,
    ) -> None:
        if max_batch < 1:
            raise ValueError("max_batch must be >= 1")
        self.adapter = adapter
        self.batch = batch
        self.max_batch = max_batch
        self.per_clause_retry = per_clause_retry
        self.fallback = fallback
        self._fallback_factory = fallback_factory
        self._fallback_engine: Any = None
        self._pass1 = pass1

    @property
    def backend(self) -> str:
        profile = f"/{self.adapter.agent}" if self.adapter.agent else ""
        return f"agent:{self.adapter.name}{profile}"

    def __call__(self, utterance: str) -> dict[str, Any]:
        return self.forward(utterance)

    def forward(self, utterance: str) -> dict[str, Any]:
        """Analyse one utterance. Raises :class:`AgentError` when the agent fails
        and fallback is off."""
        result = self._run([utterance], batch=False)[0]
        if isinstance(result, BaseException):
            raise result
        return result

    def forward_batch(self, utterances: Sequence[str]) -> list[dict[str, Any] | BaseException]:
        """Analyse a parent chunk's clauses, one result per input, in order.

        A clause that could not be analysed yields its exception in place of a
        dict, so one bad clause does not discard its siblings.
        """
        return self._run(list(utterances), batch=self.batch)

    # -- internals ---------------------------------------------------------

    def _run(self, utterances: list[str], *, batch: bool) -> list[dict[str, Any] | BaseException]:
        pass1 = [self._pass1(text) for text in utterances]
        items = [(i, text, pass1[i]) for i, text in enumerate(utterances)]
        results: dict[int, dict[str, Any] | BaseException] = {}

        size = self.max_batch if batch else 1
        agent_unusable: BaseException | None = None
        for start in range(0, len(items), size):
            chunk = items[start : start + size]
            if agent_unusable is not None:
                for index, _, _ in chunk:
                    results[index] = agent_unusable
                continue
            try:
                results.update(self._annotate(chunk))
            except AgentNotFoundError as exc:
                agent_unusable = exc
                for index, _, _ in chunk:
                    results[index] = exc
            except (AgentError, ValueError) as exc:
                logger.warning("SFL agent batch of %d failed: %s", len(chunk), exc)
                for index, _, _ in chunk:
                    results[index] = exc

        if batch and len(items) > 1 and self.per_clause_retry and agent_unusable is None:
            for index, text, p1 in items:
                if not isinstance(results.get(index), BaseException):
                    continue
                if agent_unusable is not None:
                    results[index] = agent_unusable
                    continue
                try:
                    results.update(self._annotate([(index, text, p1)]))
                except (AgentParseError, ValueError) as exc:
                    results[index] = exc
                except AgentError as exc:
                    # Timeout / crash / missing binary: retrying the rest one by
                    # one would repeat the same failure, so stop here.
                    agent_unusable = exc
                    results[index] = exc

        out: list[dict[str, Any] | BaseException] = []
        for index, text, p1 in items:
            value = results.get(index)
            if value is None:
                value = AgentParseError(self.adapter.name, f"no annotation for clause {index}")
            if isinstance(value, BaseException):
                value = self._fall_back(text, value)
            else:
                value = {"ideational": p1, "interpersonal": value, "backend": self.backend}
            out.append(value)
        return out

    def _annotate(
        self, chunk: Sequence[tuple[int, str, dict[str, Any]]]
    ) -> dict[int, dict[str, Any] | BaseException]:
        indices = [index for index, _, _ in chunk]
        result = self.adapter.run(build_prompt(chunk), schema=ANNOTATION_SCHEMA)
        found = parse_annotations(result.payload, indices)
        missing = AgentParseError(self.adapter.name, "annotation missing from batch output")
        return {index: found.get(index, missing) for index in indices}

    def _fall_back(self, utterance: str, error: BaseException) -> dict[str, Any] | BaseException:
        if not self.fallback:
            return error
        try:
            if self._fallback_engine is None:
                self._fallback_engine = self._fallback_factory()
            output = dict(self._fallback_engine.forward(utterance))
        except Exception as exc:  # noqa: BLE001 - surfaced per clause, not raised
            logger.warning("SFL DSPy fallback failed: %s", exc)
            return exc
        output["backend"] = "dspy-fallback"
        output["agent_error"] = f"{type(error).__name__}: {error}"
        return output
