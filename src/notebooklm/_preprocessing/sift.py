"""SIFT fact-check: an LLM evidence stage followed by a Jev verdict stage.

The evidence stage is a DSPy module with one signature per SIFT move (Stop,
Investigate the source, Find better coverage, Trace claims). It returns the four
step outputs and citations. It never outputs a verdict. The verdict comes from
:class:`JevClient` over that evidence.

The method text comes from ``sift.skill`` in the fact-check framework directory.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import dspy
import httpx

from notebooklm._preprocessing.jev import ChoiceQuestion, JevClient, JevError

logger = logging.getLogger(__name__)

VERDICTS = ("supported", "contradicted", "unverifiable")
DEFAULT_FRAMEWORK_PATH = "~/.syncopated/skills/fact-check"

EvidenceRunner = Callable[..., dict[str, Any]]


@dataclass
class SiftResult:
    verdict: str  # supported | contradicted | unverifiable | skipped_no_framework
    confidence: float | None = None
    probabilities: dict[str, float] | None = None
    #: keys: stop, investigate_source, find_coverage, trace_claim
    sift_steps: dict[str, Any] | None = None
    #: [{url, title, quote}]
    citations: list[dict[str, Any]] | None = None
    model: str | None = None


def web_search(query: str) -> str:
    """Search the web for sources that bear on a claim (Exa, then Jina)."""
    if exa_key := os.environ.get("EXA_API_KEY"):
        try:
            resp = httpx.post(
                "https://api.exa.ai/search",
                json={"query": query, "useAutoprompt": True},
                headers={"x-api-key": exa_key},
                timeout=10.0,
            )
            if resp.status_code == 200:
                return str(resp.json())
        except Exception as e:
            logger.warning(f"Exa search failed: {e}")

    if jina_key := os.environ.get("JINA_API_KEY"):
        try:
            resp = httpx.get(
                f"https://s.jina.ai/{query}",
                headers={"Authorization": f"Bearer {jina_key}"},
                timeout=10.0,
            )
            if resp.status_code == 200:
                return resp.text
        except Exception as e:
            logger.warning(f"Jina search failed: {e}")

    return f"No search provider returned results for: {query}"


class StopSignature(dspy.Signature):
    """SIFT move 1, Stop: before reacting, state exactly what is asserted. Restate the
    claim as one specific checkable assertion and classify its type: causal (X caused Y),
    numeric (a quantity, count or date value), attribution (who said or did it), or
    temporal (when, or in what order). Use the parent context and SFL metadata to resolve
    pronouns and implied scope. Do not judge whether the assertion is true."""

    claim = dspy.InputField(desc="The sentence or clause to check")
    parent_context = dspy.InputField(desc="Surrounding text of the parent chunk")
    sfl = dspy.InputField(desc="SFL metadata as JSON (mood, modality, tenor); may be empty")
    checkable_assertion = dspy.OutputField(
        desc="The single specific factual assertion the claim makes, stated literally"
    )
    claim_type = dspy.OutputField(desc="One of: causal, numeric, attribution, temporal")


class InvestigateSourceSignature(dspy.Signature):
    """SIFT move 2, Investigate the source: identify who makes the claim or which source
    it cites, and how reliable that source is for this kind of claim. Consider expertise,
    track record, incentives, whether it is opinion or reporting, and whether it is
    state-controlled media. Do not judge the claim itself."""

    claim = dspy.InputField(desc="The sentence or clause to check")
    parent_context = dspy.InputField(desc="Surrounding text of the parent chunk")
    source = dspy.OutputField(desc="The named or implied source of the claim, or 'none identified'")
    reliability = dspy.OutputField(
        desc="high, medium, low, or unknown for this claim, with one sentence of reason"
    )


class FindCoverageSignature(dspy.Signature):
    """SIFT move 3, Find better coverage: look for what independent sources say about the
    claim. Write specific search queries and use the web_search tool. Summarize agreement,
    disagreement and gaps among the sources. Record each source you rely on as a citation
    with its url, title and the exact quote that supports or contradicts the claim."""

    claim = dspy.InputField(desc="The sentence or clause to check")
    queries = dspy.OutputField(desc="The search queries used, as a list of strings")
    coverage_summary = dspy.OutputField(
        desc="What independent sources say about the claim: agreement, disagreement, gaps"
    )
    citations: list[dict[str, str]] = dspy.OutputField(
        desc="Sources relied on, each with keys url, title, quote"
    )


class TraceClaimSignature(dspy.Signature):
    """SIFT move 4, Trace claims: find the original source of the claim, meaning the first
    publication or primary document, not a secondhand repetition. Check whether any quoted
    words match the original wording and context. Use the coverage summary to locate
    candidate originals."""

    claim = dspy.InputField(desc="The sentence or clause to check")
    coverage_summary = dspy.InputField(desc="Summary of what other sources say")
    original_source = dspy.OutputField(
        desc="URL or citation of the earliest primary source found, or 'not found'"
    )
    quoted_accurately = dspy.OutputField(
        desc="yes, no, or not_applicable: whether the quoted words match the original"
    )


def _normalize_citations(raw: Any) -> list[dict[str, str]]:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            return []
    if not isinstance(raw, list):
        return []
    return [
        {key: str(item.get(key, "")) for key in ("url", "title", "quote")}
        for item in raw
        if isinstance(item, dict)
    ]


def _fields(pred: Any, names: tuple[str, ...]) -> dict[str, Any]:
    return {name: getattr(pred, name, None) for name in names}


class SiftEvidenceModule(dspy.Module):
    """Runs the four SIFT moves and returns ``{"sift_steps": {...}, "citations": [...]}``."""

    def __init__(self) -> None:
        super().__init__()
        self.stop = dspy.Predict(StopSignature)
        self.investigate_source = dspy.Predict(InvestigateSourceSignature)
        self.find_coverage = dspy.ReAct(FindCoverageSignature, tools=[web_search], max_iters=3)
        self.trace_claim = dspy.Predict(TraceClaimSignature)

    def forward(
        self, claim: str, parent_context: str = "", sfl: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        stop = self.stop(claim=claim, parent_context=parent_context, sfl=json.dumps(sfl or {}))
        investigate = self.investigate_source(claim=claim, parent_context=parent_context)
        coverage = self.find_coverage(claim=claim)
        trace_pred = self.trace_claim(
            claim=claim, coverage_summary=str(getattr(coverage, "coverage_summary", ""))
        )
        return {
            "sift_steps": {
                "stop": _fields(stop, ("checkable_assertion", "claim_type")),
                "investigate_source": _fields(investigate, ("source", "reliability")),
                "find_coverage": _fields(coverage, ("queries", "coverage_summary")),
                "trace_claim": _fields(trace_pred, ("original_source", "quoted_accurately")),
            },
            "citations": _normalize_citations(getattr(coverage, "citations", [])),
        }


VERDICT_QUESTION = ChoiceQuestion(
    instructions=(
        "Decide whether the claim is supported by the evidence. Use only the state: the "
        "claim, its parent context, the SIFT steps and the citations."
    ),
    criteria={
        "supported": "every factual element is backed by a cited source",
        "contradicted": "at least one cited source directly contradicts it",
        "unverifiable": "the evidence neither backs nor contradicts it",
    },
)


class SiftChecker:
    def __init__(
        self,
        jev: JevClient | None = None,
        framework_path: str | None = None,
        evidence: EvidenceRunner | None = None,
    ) -> None:
        self.framework_path = (
            framework_path
            or os.environ.get("FACT_CHECK_FRAMEWORK_PATH")
            or os.path.expanduser(DEFAULT_FRAMEWORK_PATH)
        )
        self._jev = jev or JevClient()
        self._evidence = evidence

    @property
    def framework_available(self) -> bool:
        """Whether ``sift.skill`` exists under the framework path."""
        return os.path.exists(os.path.join(self.framework_path, "sift.skill"))

    async def check(
        self, claim: str, parent_context: str, sfl: dict[str, Any] | None
    ) -> SiftResult:
        if not self.framework_available:
            return SiftResult(verdict="skipped_no_framework")

        if self._evidence is None:
            self._evidence = SiftEvidenceModule()
        evidence = self._evidence
        lm = dspy.settings.lm

        def _run_evidence() -> dict[str, Any]:
            with dspy.context(lm=lm):
                return evidence(claim=claim, parent_context=parent_context, sfl=sfl)

        gathered = await asyncio.to_thread(_run_evidence)
        sift_steps = gathered["sift_steps"]
        citations = gathered["citations"]

        decisions = await self._jev.decide(
            state={
                "claim": claim,
                "parent_context": parent_context,
                "sift_steps": sift_steps,
                "citations": citations,
            },
            questions={"verdict": VERDICT_QUESTION},
        )
        decision = decisions["verdict"]
        if decision.choice not in VERDICTS:
            raise JevError(f"Jev returned an unknown verdict: {decision.choice!r}")

        lm_name = getattr(lm, "model", None) or "unknown"
        return SiftResult(
            verdict=decision.choice,
            confidence=decision.confidence,
            probabilities=decision.probabilities,
            sift_steps=sift_steps,
            citations=citations,
            model=f"{lm_name} + {self._jev.model}",
        )
