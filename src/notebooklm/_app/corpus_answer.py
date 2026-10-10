"""Answers grounded in retrieved corpus chunks.

Three single-call paths (the cross-notebook DSPy pipeline lives in
:mod:`notebooklm._app.corpus_agent`):

* :func:`answer_notebooklm` — sends the question plus ``[C1]…[Cn]`` excerpts
  to NotebookLM ``chat.ask`` scoped to the hits' source ids;
* :func:`answer_litellm` — streams a freeform litellm model's answer token by
  token (no ``dspy.configure()``, safe in the server);
* :func:`build_prompt` / :func:`citation_map` — shared prompt and ``[Cn]``
  citation helpers.

A *hit* is a mapping with at least ``external_id``, ``text``, ``document_id``
and optionally ``notebook_id`` / ``kind`` (the rows ``corpus_explorer.search``
returns).
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from typing import Any

#: Excerpt length cap per chunk in the prompt.
EXCERPT_CHARS = 1200

_CITE_RE = re.compile(r"\[C(\d+)\]")

INSTRUCTIONS = (
    "Answer the question using only the numbered excerpts below. Cite every claim "
    "with the excerpt label in square brackets, e.g. [C1] or [C2][C4]. If the "
    "excerpts do not contain the answer, say so plainly."
)

Hit = Mapping[str, Any]


def labels_for(hits: Sequence[Hit]) -> dict[str, str]:
    """``{"C1": external_id, ...}`` in hit order."""
    return {f"C{i}": str(h["external_id"]) for i, h in enumerate(hits, start=1)}


def build_prompt(question: str, hits: Sequence[Hit]) -> tuple[str, dict[str, str]]:
    """The grounded prompt and its ``{Cn: external_id}`` label map."""
    labels = labels_for(hits)
    blocks = []
    for (label, _), hit in zip(labels.items(), hits, strict=True):
        text = str(hit["text"]).strip()
        if len(text) > EXCERPT_CHARS:
            text = text[: EXCERPT_CHARS - 1] + "…"
        blocks.append(f"[{label}] {text}")
    prompt = f"{INSTRUCTIONS}\n\nExcerpts:\n" + "\n\n".join(blocks) + f"\n\nQuestion: {question}"
    return prompt, labels


def citation_map(answer: str, labels: Mapping[str, str]) -> dict[str, str]:
    """The ``[Cn]`` labels the answer actually cites, mapped to external ids."""
    cited: dict[str, str] = {}
    for match in _CITE_RE.finditer(answer):
        label = f"C{match.group(1)}"
        if label in labels:
            cited[label] = labels[label]
    return cited


def notebooks_of(hits: Sequence[Hit]) -> list[str]:
    """Distinct notebook ids of the hits, most-hit first."""
    counts = Counter(str(h["notebook_id"]) for h in hits if h.get("notebook_id"))
    return [nb for nb, _ in counts.most_common()]


def source_ids_of(hits: Sequence[Hit]) -> list[str]:
    """Document ids of hits that are NotebookLM sources (artifacts/notes are not)."""
    seen: dict[str, None] = {}
    for h in hits:
        if h.get("kind", "source") == "source":
            seen.setdefault(str(h["document_id"]), None)
    return list(seen)


async def answer_notebooklm(
    client: Any, question: str, hits: Sequence[Hit], *, notebook_id: str | None = None
) -> dict[str, Any]:
    """Ask NotebookLM with the hits as labelled excerpts, scoped to their sources.

    ``notebook_id`` defaults to the notebook most hits come from; only that
    notebook's hits go into the prompt (``chat.ask`` covers one notebook).
    """
    if not hits:
        raise ValueError("no retrieved chunks to ground the answer in")
    nb = notebook_id or next(iter(notebooks_of(hits)), None)
    if nb is None:
        raise ValueError("retrieved chunks carry no notebook id")
    scoped = [h for h in hits if h.get("notebook_id") == nb]
    prompt, labels = build_prompt(question, scoped)
    source_ids = source_ids_of(scoped) or None
    result = await client.chat.ask(nb, prompt, source_ids=source_ids)
    answer = str(getattr(result, "answer", "") or "")
    return {
        "mode": "notebooklm",
        "notebook_id": nb,
        "answer": answer,
        "labels": labels,
        "citations": citation_map(answer, labels),
        "source_ids": source_ids,
        "conversation_id": getattr(result, "conversation_id", None),
    }


#: ``litellm.acompletion`` — injectable for tests.
Completion = Callable[..., Any]


def _default_completion() -> Completion:
    import litellm

    return litellm.acompletion


def _delta_text(chunk: Any) -> str:
    try:
        choice = chunk["choices"][0] if isinstance(chunk, dict) else chunk.choices[0]
        delta = choice["delta"] if isinstance(choice, dict) else choice.delta
        content = delta.get("content") if isinstance(delta, dict) else delta.content
    except (AttributeError, IndexError, KeyError, TypeError):
        return ""
    return content or ""


async def answer_litellm(
    model: str,
    question: str,
    hits: Sequence[Hit],
    *,
    completion: Completion | None = None,
) -> AsyncIterator[str]:
    """Yield the answer of any litellm ``model`` string token by token."""
    if not model.strip():
        raise ValueError("model must be a litellm model string, e.g. 'openrouter/…'")
    prompt, _ = build_prompt(question, hits)
    acompletion = completion or _default_completion()
    stream = await acompletion(
        model=model, messages=[{"role": "user", "content": prompt}], stream=True
    )
    async for chunk in stream:
        text = _delta_text(chunk)
        if text:
            yield text
