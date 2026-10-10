import json
from types import SimpleNamespace

import dspy
import httpx
import pytest

from notebooklm._preprocessing.jev import JevClient, JevError
from notebooklm._preprocessing.sift import (
    FindCoverageSignature,
    InvestigateSourceSignature,
    SiftChecker,
    SiftEvidenceModule,
    SiftResult,
    StopSignature,
    TraceClaimSignature,
    _normalize_citations,
    web_search,
)

SIGNATURES = (StopSignature, InvestigateSourceSignature, FindCoverageSignature, TraceClaimSignature)

STEP_DICTS = {
    "stop": {"checkable_assertion": "Rates rose 3% in 2025", "claim_type": "numeric"},
    "investigate_source": {"source": "Central bank", "reliability": "high, official data"},
    "find_coverage": {"queries": ["rates 2025"], "coverage_summary": "Sources agree on 3%"},
    "trace_claim": {"original_source": "https://bank.example/report", "quoted_accurately": "yes"},
}
CITATIONS = [{"url": "https://bank.example/report", "title": "Report", "quote": "rose 3%"}]


def _framework(tmp_path):
    (tmp_path / "sift.skill").write_bytes(b"placeholder")
    return str(tmp_path)


def _jev_returning(choice: str, calls: list, confidence=0.9, probabilities=None):
    probs = probabilities or {"supported": 0.9, "contradicted": 0.05, "unverifiable": 0.05}

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "decisions": {
                    "verdict": {"choice": choice, "confidence": confidence, "probabilities": probs}
                }
            },
        )

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return JevClient(api_key="k", http_client=http, backoff_base=0.0)


@pytest.mark.parametrize("signature", SIGNATURES)
def test_evidence_signatures_have_no_verdict_output(signature):
    outputs = set(signature.output_fields)
    assert not outputs & {"verdict", "is_valid", "label", "decision"}


def test_evidence_signatures_cover_sift_fields():
    assert set(StopSignature.output_fields) == {"checkable_assertion", "claim_type"}
    assert set(InvestigateSourceSignature.output_fields) == {"source", "reliability"}
    assert set(FindCoverageSignature.output_fields) == {"queries", "coverage_summary", "citations"}
    assert set(TraceClaimSignature.output_fields) == {"original_source", "quoted_accurately"}


async def test_missing_framework_skips_without_calling_evidence_or_jev(tmp_path):
    evidence_calls: list = []
    jev_calls: list = []

    def evidence(**kwargs):
        evidence_calls.append(kwargs)
        return {}

    checker = SiftChecker(
        jev=_jev_returning("supported", jev_calls),
        framework_path=str(tmp_path / "absent"),
        evidence=evidence,
    )

    assert checker.framework_available is False
    result = await checker.check("claim", "parent", None)

    assert result == SiftResult(verdict="skipped_no_framework")
    assert evidence_calls == []
    assert jev_calls == []


async def test_check_maps_evidence_and_jev_verdict(tmp_path):
    evidence_calls: list = []
    jev_calls: list = []

    def evidence(**kwargs):
        evidence_calls.append(kwargs)
        return {"sift_steps": STEP_DICTS, "citations": CITATIONS}

    checker = SiftChecker(
        jev=_jev_returning(
            "supported",
            jev_calls,
            confidence=0.91,
            probabilities={"supported": 0.91, "contradicted": 0.03, "unverifiable": 0.06},
        ),
        framework_path=_framework(tmp_path),
        evidence=evidence,
    )

    result = await checker.check("Rates rose 3%", "Parent text.", {"mood": "declarative"})

    assert result.verdict == "supported"
    assert result.confidence == pytest.approx(0.91)
    assert result.probabilities == pytest.approx(
        {"supported": 0.91, "contradicted": 0.03, "unverifiable": 0.06}
    )
    assert result.sift_steps == STEP_DICTS
    assert result.citations == CITATIONS
    assert result.model == "unknown + typesafe/jev-1.13"

    assert evidence_calls == [
        {"claim": "Rates rose 3%", "parent_context": "Parent text.", "sfl": {"mood": "declarative"}}
    ]
    body = jev_calls[0]
    assert body["state"] == {
        "claim": "Rates rose 3%",
        "parent_context": "Parent text.",
        "sift_steps": STEP_DICTS,
        "citations": CITATIONS,
    }
    assert set(body["questions"]["verdict"]["criteria"]) == {
        "supported",
        "contradicted",
        "unverifiable",
    }


async def test_check_rejects_unknown_verdict_label(tmp_path):
    checker = SiftChecker(
        jev=_jev_returning("maybe", []),
        framework_path=_framework(tmp_path),
        evidence=lambda **kw: {"sift_steps": STEP_DICTS, "citations": []},
    )

    with pytest.raises(JevError, match="unknown verdict"):
        await checker.check("claim", "parent", None)


def test_evidence_module_returns_four_steps_and_citations_without_verdict():
    module = SiftEvidenceModule()
    module.find_coverage = lambda claim: SimpleNamespace(
        queries=["rates 2025"],
        coverage_summary="Sources agree on 3%",
        citations=CITATIONS,
    )
    lm = dspy.utils.DummyLM(
        [
            {"checkable_assertion": "Rates rose 3% in 2025", "claim_type": "numeric"},
            {"source": "Central bank", "reliability": "high, official data"},
            {"original_source": "https://bank.example/report", "quoted_accurately": "yes"},
        ]
    )

    with dspy.context(lm=lm):
        out = module(claim="Rates rose 3%", parent_context="Parent", sfl={"mood": "declarative"})

    assert set(out) == {"sift_steps", "citations"}
    assert set(out["sift_steps"]) == {"stop", "investigate_source", "find_coverage", "trace_claim"}
    assert out["sift_steps"]["stop"]["claim_type"] == "numeric"
    assert out["sift_steps"]["trace_claim"]["original_source"] == "https://bank.example/report"
    assert out["citations"] == CITATIONS
    assert "verdict" not in json.dumps(out)


def test_normalize_citations_accepts_json_string_and_drops_extra_keys():
    raw = json.dumps([{"url": "u", "title": "t", "quote": "q", "extra": 1}, "junk"])

    assert _normalize_citations(raw) == [{"url": "u", "title": "t", "quote": "q"}]
    assert _normalize_citations("not json") == []


def test_web_search_without_keys_returns_no_results_message(monkeypatch):
    monkeypatch.delenv("EXA_API_KEY", raising=False)
    monkeypatch.delenv("JINA_API_KEY", raising=False)

    assert web_search("rates") == "No search provider returned results for: rates"


def test_framework_path_defaults_to_env(monkeypatch, tmp_path):
    monkeypatch.setenv("FACT_CHECK_FRAMEWORK_PATH", str(tmp_path))
    (tmp_path / "sift.skill").write_bytes(b"x")

    assert SiftChecker().framework_available is True
