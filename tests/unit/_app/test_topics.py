"""Tests for BERTopic fitting and topic persistence (no database)."""

from __future__ import annotations

import numpy as np
import pytest

from notebooklm._app.topics import fit_topics, load_corpus, save_topics
from notebooklm.db.models import Topic, TopicRun

VOCAB = [
    ["guitar chord melody strings", "guitar melody chord riff", "chord strings guitar solo"],
    ["orbit planet rocket launch", "rocket orbit planet telescope", "planet launch orbit probe"],
    ["bread oven flour yeast", "flour bread yeast dough", "oven dough bread crust"],
]


def _synthetic_corpus(per_cluster: int = 30, dims: int = 768, seed: int = 0):
    rng = np.random.default_rng(seed)
    centroids = rng.normal(size=(3, dims))
    centroids = 10.0 * centroids / np.linalg.norm(centroids, axis=1, keepdims=True)
    docs: list[str] = []
    vectors: list[list[float]] = []
    for cluster in range(3):
        for i in range(per_cluster):
            docs.append(VOCAB[cluster][i % len(VOCAB[cluster])])
            vec = centroids[cluster] + rng.normal(scale=0.01, size=dims)
            vectors.append(vec.tolist())
    return docs, vectors


def test_fit_topics_separates_clusters_and_labels_every_doc() -> None:
    docs, vectors = _synthetic_corpus()

    topic_numbers, topics = fit_topics(docs, vectors, min_topic_size=10)

    assert len(topic_numbers) == len(docs)
    assert all(isinstance(n, int) for n in topic_numbers)
    real_topics = [t for t in topics if t["topic_number"] != -1]
    assert len(real_topics) >= 3
    for t in topics:
        assert set(t) == {"topic_number", "label", "keywords", "size"}
        assert isinstance(t["label"], str) and t["label"]
        assert 0 < len(t["keywords"]) <= 10
        assert all(isinstance(k, str) for k in t["keywords"])
    assert sum(t["size"] for t in topics) == len(docs)


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _FakeSession:
    """Records ORM adds and executed statements; assigns ids on flush."""

    def __init__(self, rows=None) -> None:
        self.rows = rows or []
        self.added: list = []
        self.executed: list = []
        self.committed = False
        self._next_id = 1

    async def execute(self, stmt):
        self.executed.append(stmt)
        return _Result(self.rows)

    def add(self, obj) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        for obj in self.added:
            if getattr(obj, "id", None) is None:
                obj.id = self._next_id
                self._next_id += 1

    async def commit(self) -> None:
        self.committed = True


async def test_load_corpus_returns_ids_texts_and_vectors() -> None:
    rows = [
        ("doc:1:0", "alpha", np.array([1.0, 2.0])),
        ("doc:1:1", "beta", np.array([3.0, 4.0])),
        ("doc:1:1", "beta", np.array([3.0, 4.0])),
    ]
    session = _FakeSession(rows)

    ids, texts, vectors = await load_corpus(session)

    assert ids == ["doc:1:0", "doc:1:1"]
    assert texts == ["alpha", "beta"]
    assert vectors == [[1.0, 2.0], [3.0, 4.0]]


async def test_save_topics_writes_run_topics_and_clause_topic_ids() -> None:
    session = _FakeSession()
    clause_ids = ["c0", "c1", "c2"]
    topic_numbers = [0, 0, -1]
    topics = [
        {"topic_number": -1, "label": "-1_x", "keywords": ["x"], "size": 1},
        {"topic_number": 0, "label": "0_guitar", "keywords": ["guitar"], "size": 2},
    ]

    run_id = await save_topics(
        session, {"min_topic_size": 10}, "abc123", topic_numbers, topics, clause_ids
    )

    assert session.committed
    runs = [o for o in session.added if isinstance(o, TopicRun)]
    assert len(runs) == 1
    assert runs[0].id == run_id
    assert runs[0].n_docs == 3
    assert runs[0].n_topics == 1
    assert runs[0].trace_id == "abc123"
    rows = [o for o in session.added if isinstance(o, Topic)]
    assert [(r.run_id, r.topic_number, r.label, r.size) for r in rows] == [
        (run_id, -1, "-1_x", 1),
        (run_id, 0, "0_guitar", 2),
    ]
    assert len(session.executed) == 2
    assigned: dict[int, list[str]] = {}
    for stmt in session.executed:
        params = stmt.compile().params
        assigned[params["topic_id"]] = params["external_id_1"]
    assert assigned == {rows[0].id: ["c2"], rows[1].id: ["c0", "c1"]}


async def test_save_topics_rejects_length_mismatch() -> None:
    with pytest.raises(ValueError, match="differ in length"):
        await save_topics(_FakeSession(), {}, None, [0, 1], [], ["only-one"])
