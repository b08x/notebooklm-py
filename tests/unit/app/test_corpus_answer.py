"""Grounded answers: NotebookLM scoping, litellm streaming, DSPy corpus pipeline (facts 27-29, 60-61, 63)."""

from __future__ import annotations

import threading
from types import SimpleNamespace
from typing import Any

import dspy
import pytest
from dspy.utils import DummyLM

from notebooklm._app import corpus_agent, corpus_answer

HITS = [
    {
        "external_id": "s1:1:0",
        "text": "Kernel panics hit cgroup limits.",
        "document_id": "s1",
        "notebook_id": "nb1",
    },
    {
        "external_id": "a1:2:0",
        "text": "OOM killer picks the largest RSS.",
        "document_id": "a1",
        "notebook_id": "nb1",
        "kind": "audio",
    },
    {"external_id": "s2:3:0", "text": "x" * 2000, "document_id": "s2", "notebook_id": "nb2"},
]


class _Chat:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, Any]] = []

    async def ask(self, notebook_id: str, question: str, source_ids: Any = None) -> Any:
        self.calls.append((notebook_id, question, source_ids))
        return SimpleNamespace(
            answer="Panics come from cgroups [C1] and OOM [C2] [C9].", conversation_id="conv"
        )


def test_build_prompt_labels_and_truncates() -> None:
    prompt, labels = corpus_answer.build_prompt("Why?", HITS)
    assert labels == {"C1": "s1:1:0", "C2": "a1:2:0", "C3": "s2:3:0"}
    assert "[C1] Kernel panics" in prompt and "[C3] " + "x" * 10 in prompt
    assert "x" * 1300 not in prompt and prompt.endswith("Question: Why?")


@pytest.mark.asyncio
async def test_answer_notebooklm_scopes_sources_and_maps_citations() -> None:
    chat = _Chat()
    out = await corpus_answer.answer_notebooklm(SimpleNamespace(chat=chat), "Why?", HITS)
    nb, prompt, source_ids = chat.calls[0]
    assert nb == "nb1"
    # Only the notebook's hits; artifacts are not NotebookLM sources.
    assert source_ids == ["s1"]
    assert "[C1] Kernel panics" in prompt and "[C2] OOM" in prompt and "[C3]" not in prompt
    assert out["citations"] == {"C1": "s1:1:0", "C2": "a1:2:0"}
    assert out["conversation_id"] == "conv"


@pytest.mark.asyncio
async def test_answer_notebooklm_errors() -> None:
    client = SimpleNamespace(chat=_Chat())
    with pytest.raises(ValueError):
        await corpus_answer.answer_notebooklm(client, "q", [])
    with pytest.raises(ValueError):
        await corpus_answer.answer_notebooklm(
            client, "q", [{"external_id": "x", "text": "t", "document_id": "d"}]
        )
    out = await corpus_answer.answer_notebooklm(client, "q", [{**HITS[1]}], notebook_id="nb1")
    assert out["source_ids"] is None  # no source hits → whole notebook


class _Stream:
    def __init__(self, parts: list[Any]) -> None:
        self.parts = parts

    def __aiter__(self):
        async def gen():
            for p in self.parts:
                yield p

        return gen()


@pytest.mark.asyncio
async def test_answer_litellm_streams_tokens() -> None:
    seen: dict[str, Any] = {}

    async def fake_completion(**kwargs: Any) -> Any:
        seen.update(kwargs)
        return _Stream(
            [
                {"choices": [{"delta": {"content": "Hel"}}]},
                SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="lo"))]),
                {"choices": [{"delta": {}}]},
                {"bogus": True},
            ]
        )

    tokens = [
        t
        async for t in corpus_answer.answer_litellm(
            "openrouter/x", "q", HITS[:1], completion=fake_completion
        )
    ]
    assert tokens == ["Hel", "lo"]
    assert seen["stream"] is True and seen["model"] == "openrouter/x"
    assert "[C1]" in seen["messages"][0]["content"]
    with pytest.raises(ValueError):
        async for _ in corpus_answer.answer_litellm(" ", "q", HITS):
            pass


def _tools(calls: list[str]) -> corpus_agent.CorpusTools:
    async def search(q: str) -> list[dict[str, Any]]:
        calls.append(f"search:{q}:{threading.current_thread() is threading.main_thread()}")
        return [{"external_id": "s1:1:0", "text": "found"}]

    async def detail(eid: str) -> dict[str, Any]:
        calls.append(f"detail:{eid}")
        return {"text": "t", "parent": {"text": "p"}}

    async def neighbors(eid: str) -> list[dict[str, Any]]:
        calls.append(f"neighbors:{eid}")
        return []

    async def ask(nb: str, q: str) -> str:
        calls.append(f"ask:{nb}")
        return "nlm says"

    return corpus_agent.CorpusTools(search, detail, neighbors, ask)


@pytest.mark.asyncio
async def test_sync_tools_bridge_to_loop() -> None:
    import asyncio

    calls: list[str] = []
    loop = asyncio.get_running_loop()
    fns = corpus_agent.sync_tools(_tools(calls), loop, "nb1")

    def run_all() -> list[str]:
        return [fns[0]("q"), fns[1]("e"), fns[2]("e"), fns[3]("q")]

    out = await asyncio.to_thread(run_all)
    assert "found" in out[0] and "Parent passage:\np" in out[1] and out[3] == "nlm says"
    assert calls == ["search:q:True", "detail:e", "neighbors:e", "ask:nb1"]


@pytest.mark.asyncio
async def test_answer_corpus_real_react_and_mcc(monkeypatch: pytest.MonkeyPatch) -> None:
    """Two notebooks → two ReAct agents (each calling a tool) merged by MultiChainComparison."""

    def no_configure(*a: Any, **k: Any) -> None:
        raise AssertionError("dspy.configure must not be called by the pipeline")

    monkeypatch.setattr(dspy, "configure", no_configure)
    react_turns = [
        {
            "next_thought": "search",
            "next_tool_name": "search_corpus",
            "next_tool_args": {"query": "q"},
        },
        {"next_thought": "done", "next_tool_name": "finish", "next_tool_args": {}},
        {"reasoning": "nb1 reasoning", "answer": "nb1 says [C1]"},
    ]
    lm = DummyLM(
        [
            *react_turns,
            *react_turns,
            {"rationale": "merged", "answer": "Merged answer [C1] and [C3]."},
        ]
    )
    calls: list[str] = []
    out = await corpus_agent.answer_corpus("q", HITS, _tools(calls), lm=lm)
    assert out["mode"] == "corpus_agent"
    assert out["notebooks"] == ["nb1", "nb2"]
    assert len(out["per_notebook"]) == 2
    assert out["answer"] == "Merged answer [C1] and [C3]."
    assert out["citations"] == {"C1": "s1:1:0", "C3": "s2:3:0"}
    assert calls.count("search:q:True") == 2  # tool ran on the main loop thread


@pytest.mark.asyncio
async def test_answer_corpus_single_notebook_skips_merge() -> None:
    class FakeReact:
        def __init__(self, sig: Any, tools: list[Any], max_iters: int) -> None:
            assert [t.__name__ for t in tools] == [
                "search_corpus",
                "chunk_detail",
                "neighbors",
                "ask_notebook",
            ]

        def __call__(self, **kw: Any) -> Any:
            assert "[C1]" in kw["context"]
            return SimpleNamespace(answer="only [C2]", reasoning="r")

    def no_mcc(*a: Any, **k: Any) -> Any:
        raise AssertionError("single notebook needs no merge")

    out = await corpus_agent.answer_corpus(
        "q", HITS[:2], _tools([]), lm=object(), react_factory=FakeReact, mcc_factory=no_mcc
    )
    assert out["answer"] == "only [C2]" and out["citations"] == {"C2": "a1:2:0"}


@pytest.mark.asyncio
async def test_answer_corpus_requires_lm_and_hits(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ValueError):
        await corpus_agent.answer_corpus("q", [], _tools([]), lm=object())
    with dspy.context(lm=None), pytest.raises(corpus_agent.AgentUnavailableError):
        await corpus_agent.answer_corpus("q", HITS, _tools([]))


@pytest.mark.asyncio
async def test_deep_mode_unavailable_without_sandbox() -> None:
    with pytest.raises(corpus_agent.DeepModeUnavailableError) as err:
        await corpus_agent.answer_deep("q", HITS, lm=object(), sandbox_check=lambda: False)
    assert err.value.code == "deep_mode_unavailable"


@pytest.mark.asyncio
async def test_deep_mode_runs_rlm_under_context() -> None:
    seen: dict[str, Any] = {}

    class FakeRLM:
        def __init__(self, sig: str, max_iters: int) -> None:
            seen["sig"] = sig

        def __call__(self, **kw: Any) -> Any:
            seen["lm"] = dspy.settings.lm
            return SimpleNamespace(answer="deep [C2]")

    lm = object()
    out = await corpus_agent.answer_deep(
        "q", HITS, lm=lm, rlm_factory=FakeRLM, sandbox_check=lambda: True
    )
    assert out["experimental"] is True and out["citations"] == {"C2": "a1:2:0"}
    assert seen["lm"] is lm and seen["sig"] == "context, question -> answer"
    with dspy.context(lm=None), pytest.raises(corpus_agent.AgentUnavailableError):
        await corpus_agent.answer_deep("q", HITS, sandbox_check=lambda: True)


def test_deno_available_returns_bool() -> None:
    assert isinstance(corpus_agent.deno_available(), bool)
