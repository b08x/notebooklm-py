"""Deterministic spaCy features stored on every child clause.

``tokens``: one dict per token — text, lemma, pos, tag, dep, head (index within
the child), morph (feature dict). ``groups``: noun chunks plus clause groups
(the subtree of each clausal head). ``root_index``: index of the first ROOT.
The Ingest mode's token/deps/groups panes and the fact-check gate read these.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

#: Dependency labels whose (verbal) head starts a clause group.
CLAUSE_DEPS = frozenset({"ROOT", "ccomp", "xcomp", "advcl", "relcl", "acl", "conj", "parataxis"})


@dataclass
class ClauseFeatures:
    tokens: list[dict[str, Any]]
    groups: dict[str, list[dict[str, Any]]]
    root_index: int | None


def _doc_features(doc: Any) -> ClauseFeatures:
    tokens = [
        {
            "text": tok.text,
            "lemma": tok.lemma_,
            "pos": tok.pos_,
            "tag": tok.tag_,
            "dep": tok.dep_,
            "head": tok.head.i,
            "morph": tok.morph.to_dict(),
        }
        for tok in doc
    ]
    noun_chunks = [
        {"text": nc.text, "start": nc.start, "end": nc.end, "root": nc.root.i}
        for nc in doc.noun_chunks
    ]
    clauses = []
    for tok in doc:
        if tok.dep_ in CLAUSE_DEPS and tok.pos_ in ("VERB", "AUX"):
            start, end = tok.left_edge.i, tok.right_edge.i + 1
            clauses.append(
                {
                    "head": tok.i,
                    "dep": tok.dep_,
                    "start": start,
                    "end": end,
                    "text": doc[start:end].text,
                }
            )
    root_index = next((tok.i for tok in doc if tok.dep_ == "ROOT"), None)
    return ClauseFeatures(
        tokens=tokens,
        groups={"noun_chunks": noun_chunks, "clauses": clauses},
        root_index=root_index,
    )


def extract(texts: Iterable[str], nlp: Any | None = None) -> list[ClauseFeatures]:
    """Parse ``texts`` with spaCy (batched) and return one feature set per text."""
    if nlp is None:
        from .chunking.recursive import load_spacy

        nlp = load_spacy()
    return [_doc_features(doc) for doc in nlp.pipe(list(texts))]
