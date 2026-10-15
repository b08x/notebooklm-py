"""``AgentSFLEngine``: hybrid pass-1/pass-2, parent-chunk batching, fallbacks.

The adapter is a scripted fake; pass 1 and the DSPy fallback are injected, so
no agent binary, spaCy model or LM is needed.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from typing import Any

import pytest

from notebooklm._preprocessing.cli_agents import (
    AgentNotFoundError,
    AgentResult,
    AgentSFLEngine,
    AgentTimeoutError,
    CLIAgentAdapter,
)
from notebooklm._preprocessing.cli_agents.sfl_engine import (
    ANNOTATION_SCHEMA,
    build_prompt,
    parse_annotations,
)


def _clauses(prompt: str) -> list[dict[str, Any]]:
    return json.loads(prompt.split("Clauses:\n", 1)[1])


def _indices(prompt: str) -> list[int]:
    clauses = _clauses(prompt)
    return [c["index"] for c in clauses]


def _annotation(index: int) -> dict[str, Any]:
    return {"index": index, "mood": "declarative", "modality": "none", "tenor": "neutral"}


class ScriptedAdapter(CLIAgentAdapter):
    """Answers each prompt with ``respond(indices)``; records prompts and schemas."""

    name = "fake"
    binary = "fake"

    def __init__(self, respond: Callable[[list[int]], Any]) -> None:
        super().__init__(which=lambda _: "/bin/fake")
        self.respond = respond
        self.calls: list[list[int]] = []
        self.schemas: list[Mapping[str, Any] | None] = []

    def build_argv(self, executable: str, prompt: str, schema: Any) -> list[str]:
        return [executable, prompt]

    def extract_text(self, stdout: str) -> str:
        return stdout

    def run(self, prompt: str, *, schema: Mapping[str, Any] | None = None) -> AgentResult:
        indices = _indices(prompt)
        self.calls.append(indices)
        self.schemas.append(schema)
        payload = self.respond(indices)
        if isinstance(payload, BaseException):
            raise payload
        return AgentResult("fake", json.dumps(payload), payload, "", 0.0)


def all_ok(indices: list[int]) -> Any:
    return {"annotations": [_annotation(i) for i in indices]}


class FakeDSPy:
    def __init__(self) -> None:
        self.seen: list[str] = []

    def forward(self, utterance: str) -> dict[str, Any]:
        self.seen.append(utterance)
        return {"ideational": {"dspy": True}, "interpersonal": {"tenor": "formal"}}


def pass1(text: str) -> dict[str, Any]:
    return {"participants": [text], "processes": [], "circumstances": []}


def make(adapter: CLIAgentAdapter, **kwargs: Any) -> tuple[AgentSFLEngine, FakeDSPy]:
    dspy = FakeDSPy()
    engine = AgentSFLEngine(adapter, pass1=pass1, fallback_factory=lambda: dspy, **kwargs)
    return engine, dspy


def test_forward_combines_spacy_pass1_with_agent_pass2() -> None:
    adapter = ScriptedAdapter(all_ok)
    engine, _ = make(adapter)
    out = engine.forward("The cat sat.")
    assert out == {
        "ideational": {"participants": ["The cat sat."], "processes": [], "circumstances": []},
        "interpersonal": {"mood": "declarative", "modality": "none", "tenor": "neutral"},
        "backend": "agent:fake",
    }
    assert adapter.schemas == [ANNOTATION_SCHEMA]
    assert engine("x")["backend"] == "agent:fake"  # __call__ aliases forward


def test_batch_sends_one_prompt_per_parent() -> None:
    adapter = ScriptedAdapter(all_ok)
    engine, dspy = make(adapter)
    outs = engine.forward_batch(["a", "b", "c"])
    assert adapter.calls == [[0, 1, 2]]
    assert [o["ideational"]["participants"] for o in outs] == [["a"], ["b"], ["c"]]  # type: ignore[index]
    assert dspy.seen == []


def test_large_parent_is_split_into_max_batch_prompts() -> None:
    adapter = ScriptedAdapter(all_ok)
    engine, _ = make(adapter, max_batch=2)
    assert len(engine.forward_batch(["a", "b", "c", "d", "e"])) == 5
    assert adapter.calls == [[0, 1], [2, 3], [4]]


def test_no_batch_mode_prompts_per_clause() -> None:
    adapter = ScriptedAdapter(all_ok)
    engine, _ = make(adapter, batch=False)
    engine.forward_batch(["a", "b"])
    assert adapter.calls == [[0], [1]]


def test_missing_annotation_is_retried_per_clause() -> None:
    def drop_one(indices: list[int]) -> Any:
        return {"annotations": [_annotation(i) for i in indices if i != 1 or len(indices) == 1]}

    adapter = ScriptedAdapter(drop_one)
    engine, dspy = make(adapter)
    outs = engine.forward_batch(["a", "b", "c"])
    assert adapter.calls == [[0, 1, 2], [1]]
    assert all(o["backend"] == "agent:fake" for o in outs)  # type: ignore[index]
    assert dspy.seen == []


def test_unparseable_batch_falls_back_to_per_clause() -> None:
    def garbage_batches(indices: list[int]) -> Any:
        return "no annotations here" if len(indices) > 1 else all_ok(indices)

    adapter = ScriptedAdapter(garbage_batches)
    engine, _ = make(adapter)
    outs = engine.forward_batch(["a", "b"])
    assert adapter.calls == [[0, 1], [0], [1]]
    assert all(not isinstance(o, BaseException) for o in outs)


def test_timeout_stops_retries_and_uses_dspy_fallback() -> None:
    adapter = ScriptedAdapter(lambda idx: AgentTimeoutError("fake", "timed out"))
    engine, dspy = make(adapter)
    outs = engine.forward_batch(["a", "b", "c"])
    assert adapter.calls == [[0, 1, 2], [0]]  # one retry, then the agent is treated as down
    assert dspy.seen == ["a", "b", "c"]
    for out in outs:
        assert isinstance(out, dict)
        assert out["backend"] == "dspy-fallback"
        assert out["agent_error"].startswith("AgentTimeoutError")


def test_missing_binary_skips_retries_and_falls_back() -> None:
    adapter = ScriptedAdapter(lambda idx: AgentNotFoundError("fake", "not on PATH"))
    engine, dspy = make(adapter, max_batch=1)
    outs = engine.forward_batch(["a", "b"])
    assert adapter.calls == [[0]]
    assert dspy.seen == ["a", "b"]
    assert [o["backend"] for o in outs] == ["dspy-fallback", "dspy-fallback"]  # type: ignore[index]


def test_fallback_disabled_returns_per_clause_errors() -> None:
    adapter = ScriptedAdapter(lambda idx: AgentTimeoutError("fake", "timed out"))
    engine, dspy = make(adapter, fallback=False)
    outs = engine.forward_batch(["a", "b"])
    assert all(isinstance(o, AgentTimeoutError) for o in outs)
    assert dspy.seen == []
    with pytest.raises(AgentTimeoutError):
        engine.forward("a")


def test_fallback_engine_failure_is_returned_not_raised() -> None:
    class Broken:
        def forward(self, utterance: str) -> dict[str, Any]:
            raise RuntimeError("no LM configured")

    adapter = ScriptedAdapter(lambda idx: AgentTimeoutError("fake", "t"))
    engine = AgentSFLEngine(adapter, pass1=pass1, fallback_factory=Broken)
    [out] = engine.forward_batch(["a"])
    assert isinstance(out, RuntimeError)


def test_parse_annotations_shapes() -> None:
    assert parse_annotations([_annotation(5)], [5]) == {
        5: {"mood": "declarative", "modality": "none", "tenor": "neutral"}
    }
    # single bare object for a one-clause prompt
    assert parse_annotations({"mood": "imperative"}, [3]) == {3: {"mood": "imperative"}}
    # missing / bogus indices fall back to position
    assert parse_annotations(
        {"annotations": [{"mood": "a"}, {"index": "x", "mood": "b"}]}, [7, 8]
    ) == {
        7: {"mood": "a"},
        8: {"mood": "b"},
    }
    with pytest.raises(ValueError):
        parse_annotations({"something": 1}, [0])
    with pytest.raises(ValueError):
        parse_annotations({"annotations": ["not a dict"]}, [0])


def test_build_prompt_lists_clauses_with_pass1() -> None:
    prompt = build_prompt([(0, "Hi there.", {"participants": ["Hi"]})])
    clauses = _clauses(prompt)
    assert clauses == [
        {"index": 0, "utterance": "Hi there.", "pass1_analysis": {"participants": ["Hi"]}}
    ]
    for label in ("interrogative_polar", "median", "slang", "theme", "rheme", "cohesive_markers"):
        assert label in prompt


def test_schema_enforces_skill_taxonomy() -> None:
    item = ANNOTATION_SCHEMA["properties"]["annotations"]["items"]
    assert item["required"] == [
        "index",
        "mood",
        "modality",
        "tenor",
        "theme",
        "rheme",
        "cohesive_markers",
    ]
    assert item["properties"]["mood"]["enum"] == [
        "declarative",
        "interrogative_polar",
        "interrogative_wh",
        "imperative",
        "exclamative",
        "fragment",
    ]
    assert item["properties"]["modality"]["enum"] == ["low", "median", "high", "neutral"]


def test_backend_label_includes_agent_profile() -> None:
    adapter = ScriptedAdapter(all_ok)
    adapter.agent = "sfl-annotator"
    engine, _ = make(adapter)
    assert engine.backend == "agent:fake/sfl-annotator"
    assert engine.forward("x")["backend"] == "agent:fake/sfl-annotator"


def test_max_batch_must_be_positive() -> None:
    with pytest.raises(ValueError):
        AgentSFLEngine(ScriptedAdapter(all_ok), max_batch=0)
