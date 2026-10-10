"""Cross-notebook DSPy answer pipeline and the experimental Deep (RLM) mode.

When retrieved chunks span several notebooks, NotebookLM ``chat.ask`` can only
see one of them at a time. :func:`answer_corpus` therefore:

1. runs one ``dspy.ReAct(CorpusAnswer)`` agent per notebook, with tools for
   corpus search, chunk detail, neighbors and a NotebookLM ask scoped to that
   notebook;
2. merges the per-notebook answers with ``dspy.MultiChainComparison`` into one
   answer citing the shared ``[C1]…[Cn]`` labels.

:func:`answer_deep` explores the full hit set through ``dspy.RLM``'s sandboxed
REPL. It needs the Deno-based interpreter; without it, it raises
:class:`DeepModeUnavailableError`.

Threading rule (CLAUDE.md): ``dspy.configure()`` is never called here. The
pipeline runs in ``asyncio.to_thread`` under ``dspy.context(lm=...)`` with the
LM the server configured once on its main thread. Tools are plain async
functions bridged back onto the caller's loop with
``asyncio.run_coroutine_threadsafe`` (DB sessions and the NotebookLM client are
bound to that loop).
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import shutil
from collections.abc import Callable, Coroutine, Sequence
from dataclasses import dataclass
from typing import Any

import dspy

from .corpus_answer import Hit, build_prompt, citation_map, labels_for, notebooks_of

#: Seconds a bridged tool call may take before the agent gives up on it.
TOOL_TIMEOUT = 120.0


class CorpusAnswer(dspy.Signature):
    """Answer the question from the labelled corpus excerpts, using tools to look further.

    Cite every claim with excerpt labels like [C1]; never invent labels.
    """

    question: str = dspy.InputField()
    context: str = dspy.InputField(desc="Labelled excerpts [C1]…[Cn] retrieved from the corpus")
    answer: str = dspy.OutputField(desc="A concise answer with [Cn] citations")


class AgentUnavailableError(RuntimeError):
    """No language model is configured for the DSPy pipeline."""


class DeepModeUnavailableError(RuntimeError):
    """``dspy.RLM``'s sandbox (Deno) is not installed."""

    code = "deep_mode_unavailable"


@dataclass
class CorpusTools:
    """Async tool implementations, bound to the caller's event loop."""

    search: Callable[[str], Coroutine[Any, Any, list[dict[str, Any]]]]
    detail: Callable[[str], Coroutine[Any, Any, dict[str, Any]]]
    neighbors: Callable[[str], Coroutine[Any, Any, list[dict[str, Any]]]]
    ask_notebook: Callable[[str, str], Coroutine[Any, Any, str]]


def _bridge(loop: asyncio.AbstractEventLoop, coro: Coroutine[Any, Any, Any]) -> Any:
    future: concurrent.futures.Future[Any] = asyncio.run_coroutine_threadsafe(coro, loop)
    return future.result(timeout=TOOL_TIMEOUT)


def _brief(rows: Sequence[dict[str, Any]], limit: int = 8) -> str:
    return "\n".join(
        f"- {r.get('external_id')}: {str(r.get('text', ''))[:300]}" for r in rows[:limit]
    )


def sync_tools(
    tools: CorpusTools, loop: asyncio.AbstractEventLoop, notebook_id: str
) -> list[Callable[..., str]]:
    """Synchronous ReAct tools that run ``tools`` on ``loop`` from a worker thread."""

    def search_corpus(query: str) -> str:
        """Search the whole local corpus (hybrid keyword + vector). Returns chunk ids and text."""
        return _brief(_bridge(loop, tools.search(query)))

    def chunk_detail(external_id: str) -> str:
        """Read one chunk with its parent passage and neighbouring lines."""
        d = _bridge(loop, tools.detail(external_id))
        parent = (d.get("parent") or {}).get("text", "")
        return f"{d.get('text', '')}\n\nParent passage:\n{parent}"

    def neighbors(external_id: str) -> str:
        """List chunks whose embeddings are closest to the given chunk."""
        return _brief(_bridge(loop, tools.neighbors(external_id)))

    def ask_notebook(question: str) -> str:
        """Ask NotebookLM itself, scoped to this notebook's sources."""
        return str(_bridge(loop, tools.ask_notebook(notebook_id, question)))

    return [search_corpus, chunk_detail, neighbors, ask_notebook]


def _reasoning(pred: Any) -> str:
    return str(getattr(pred, "reasoning", "") or getattr(pred, "rationale", "") or "considered")


async def answer_corpus(
    question: str,
    hits: Sequence[Hit],
    tools: CorpusTools,
    *,
    lm: Any = None,
    react_factory: Callable[..., Any] = dspy.ReAct,
    mcc_factory: Callable[..., Any] = dspy.MultiChainComparison,
    max_iters: int = 4,
) -> dict[str, Any]:
    """Per-notebook ReAct agents merged by MultiChainComparison.

    Must be awaited on the loop that ``tools`` are bound to.
    """
    if not hits:
        raise ValueError("no retrieved chunks to ground the answer in")
    bound_lm = lm if lm is not None else dspy.settings.lm
    if bound_lm is None:
        raise AgentUnavailableError("no DSPy language model is configured")
    loop = asyncio.get_running_loop()
    labels = labels_for(hits)
    label_of = {v: k for k, v in labels.items()}
    notebooks = notebooks_of(hits) or [""]

    def _context(nb_hits: Sequence[Hit]) -> str:
        return "\n\n".join(
            f"[{label_of[str(h['external_id'])]}] {str(h['text']).strip()}" for h in nb_hits
        )

    full_context = _context(hits)

    def _run() -> dict[str, Any]:
        with dspy.context(lm=bound_lm):
            per_notebook = []
            for nb in notebooks:
                nb_hits = [h for h in hits if (h.get("notebook_id") or "") == nb] or list(hits)
                agent = react_factory(
                    CorpusAnswer, tools=sync_tools(tools, loop, nb), max_iters=max_iters
                )
                pred = agent(question=question, context=_context(nb_hits))
                per_notebook.append(
                    {"notebook_id": nb, "answer": str(pred.answer), "reasoning": _reasoning(pred)}
                )
            if len(per_notebook) == 1:
                return {"answer": per_notebook[0]["answer"], "per_notebook": per_notebook}
            merger = mcc_factory(CorpusAnswer, M=len(per_notebook))
            merged = merger(
                completions=[
                    {"reasoning": p["reasoning"], "answer": p["answer"]} for p in per_notebook
                ],
                question=question,
                context=full_context,
            )
            return {"answer": str(merged.answer), "per_notebook": per_notebook}

    result = await asyncio.to_thread(_run)
    return {
        "mode": "corpus_agent",
        "answer": result["answer"],
        "labels": labels,
        "citations": citation_map(result["answer"], labels),
        "per_notebook": result["per_notebook"],
        "notebooks": notebooks,
    }


def deno_available() -> bool:
    """Whether ``dspy.RLM``'s Deno sandbox can start."""
    try:
        from deno import find_deno_bin

        return bool(find_deno_bin())
    except Exception:  # noqa: BLE001 - optional dependency probe
        return shutil.which("deno") is not None


async def answer_deep(
    question: str,
    hits: Sequence[Hit],
    *,
    lm: Any = None,
    rlm_factory: Callable[..., Any] | None = None,
    sandbox_check: Callable[[], bool] = deno_available,
) -> dict[str, Any]:
    """Experimental: let ``dspy.RLM`` explore the whole hit set in its REPL."""
    if not sandbox_check():
        raise DeepModeUnavailableError(
            "Deep mode needs the Deno sandbox for dspy.RLM; install Deno (https://deno.com) "
            "or `pip install deno`"
        )
    bound_lm = lm if lm is not None else dspy.settings.lm
    if bound_lm is None:
        raise AgentUnavailableError("no DSPy language model is configured")
    prompt, labels = build_prompt(question, hits)
    factory = rlm_factory or dspy.RLM

    def _run() -> str:
        with dspy.context(lm=bound_lm):
            rlm = factory("context, question -> answer", max_iters=10)
            return str(rlm(context=prompt, question=question).answer)

    answer = await asyncio.to_thread(_run)
    return {
        "mode": "deep",
        "experimental": True,
        "answer": answer,
        "labels": labels,
        "citations": citation_map(answer, labels),
    }
