"""Ingest and Fact-check modes: renderers, layouts, and key routing."""

from __future__ import annotations

import io

from rich.console import Console, RenderableType

from notebooklm.tui.app import layout_mode
from notebooklm.tui.keypress import handle_key
from notebooklm.tui.layout import build_layout
from notebooklm.tui.renderers.factcheck import render_factcheck
from notebooklm.tui.renderers.ingest import render_ingest
from notebooklm.tui.state import Mode, TUIState
from notebooklm.tui.theme import THEME
from notebooklm.tui.views import corpus_view


def _plain(renderable: RenderableType) -> str:
    console = Console(file=io.StringIO(), width=160, color_system=None, theme=THEME)
    console.print(renderable)
    return console.file.getvalue()


TOKENS = [
    {
        "text": "The",
        "lemma": "the",
        "pos": "DET",
        "tag": "DT",
        "dep": "det",
        "head": 1,
        "morph": {"Definite": "Def"},
    },
    {
        "text": "model",
        "lemma": "model",
        "pos": "NOUN",
        "tag": "NN",
        "dep": "nsubj",
        "head": 2,
        "morph": {"Number": "Sing"},
    },
    {
        "text": "asserts",
        "lemma": "assert",
        "pos": "VERB",
        "tag": "VBZ",
        "dep": "ROOT",
        "head": 2,
        "morph": {"Tense": "Pres"},
    },
]
RUN = {
    "id": 7,
    "document_id": "doc-a",
    "strategy": "recursive",
    "n_parents": 1,
    "n_children": 2,
    "is_active": True,
    "source_hash": "h",
    "mean_len": 10.0,
    "p95_len": 12.0,
    "entity_vetoes": 1,
    "chunker_version": "1",
}


def _ingest_state() -> TUIState:
    state = TUIState()
    state.mode = Mode.INGEST
    state.selected_notebook = "nb-1"
    state.ingest_view.update(
        notebook_id="nb-1",
        runs=[RUN],
        parents={
            7: [{"id": 70, "index": 0, "text": "The model asserts. It helps.", "n_children": 2}]
        },
        children={
            70: [
                {
                    "external_id": "doc-a:7:0",
                    "text": "The model asserts.",
                    "tokens": TOKENS,
                    "groups": {
                        "noun_chunks": [{"text": "The model"}],
                        "clauses": [{"dep": "ROOT", "text": "The model asserts"}],
                    },
                    "sfl": {"mood": "declarative", "modality": "high", "tenor": "expert"},
                    "topic": "3_models",
                },
                {
                    "external_id": "doc-a:7:1",
                    "text": "It helps.",
                    "tokens": [],
                    "groups": {},
                    "sfl": None,
                    "topic": None,
                },
            ]
        },
    )
    return state


def test_layouts_have_mode_slots() -> None:
    ingest = build_layout(Mode.INGEST)
    for name in ("modebar", "ingest_tree", "ingest_children", "ingest_detail"):
        assert ingest.get(name) is not None
    fc = build_layout(Mode.FACT_CHECK)
    for name in ("fc_claims", "fc_sift", "fc_evidence"):
        assert fc.get(name) is not None
    assert ingest.get("sidebar") is None and fc.get("sidebar") is None


def test_ingest_tree_children_and_deps_table() -> None:
    state = _ingest_state()
    state.ingest_view["detail"] = "deps"
    tree, kids, detail = render_ingest(state)
    tree_text, kids_text, detail_text = _plain(tree), _plain(kids), _plain(detail)
    assert "doc-a" in tree_text and "p0" in tree_text and "2c" in tree_text
    assert "The model asserts." in kids_text and "[3_models]" in kids_text
    for header in ("token", "POS", "dep", "→ head", "morphology"):
        assert header in detail_text
    assert "→ asserts" in detail_text and "Number=Sing" in detail_text


def test_detail_toggles_switch_panes() -> None:
    state = _ingest_state()
    handle_key("g", state)
    assert "noun chunks" in _plain(render_ingest(state)[2])
    handle_key("f", state)
    out = _plain(render_ingest(state)[2])
    assert "declarative" in out and "expert" in out
    handle_key("t", state)
    assert "lemma" in _plain(render_ingest(state)[2])
    state.ingest_view["child_cursor"] = 1
    handle_key("f", state)
    assert "Not tagged" in _plain(render_ingest(state)[2])


def test_compare_shows_two_runs(monkeypatch) -> None:
    state = _ingest_state()
    monkeypatch.setattr(corpus_view, "load_compare", lambda s: None)
    handle_key("x", state)
    older = {**RUN, "id": 5, "strategy": "cluster_semantic", "is_active": False, "n_children": 3}
    state.ingest_view["compare"] = {"document_id": "doc-a", "runs": [RUN, older]}
    out = _plain(render_ingest(state)[2])
    assert "run 7 recursive ●" in out and "run 5 cluster_semantic" in out
    assert "n_children" in out and "same source text" in out
    handle_key("\x1b", state)
    assert not state.ingest_view["show_compare"]


class _Store:
    def __init__(self) -> None:
        self.enqueued: list[tuple] = []

    def enqueue(self, kind, notebook_id=None, payload=None):
        self.enqueued.append((kind, notebook_id, payload))
        return "id"


def test_ingest_keys_queue_jobs_and_picker() -> None:
    state = _ingest_state()
    store = _Store()
    state.job_store = store
    handle_key("s", state)
    handle_key("F", state)
    handle_key("T", state)
    handle_key("r", state)
    assert state.ingest_view["picker"]
    assert "cluster_semantic" in _plain(render_ingest(state)[2])
    handle_key("j", state)
    handle_key("\r", state)
    kinds = [(k, nb) for k, nb, _ in store.enqueued]
    assert kinds == [
        ("sfl_tag", "nb-1"),
        ("fact_check", "nb-1"),
        ("topic_model", None),
        ("ingest", "nb-1"),
    ]
    assert store.enqueued[-1][2]["strategy"] == "cluster_semantic"
    assert not state.ingest_view["picker"]


def test_number_and_quit_keys_still_global_in_ingest() -> None:
    state = _ingest_state()
    handle_key("5", state)
    assert state.mode == Mode.JOBS
    assert handle_key("q", _ingest_state()) is False


CLAIMS = [
    {
        "external_id": "d:1:0",
        "text": "Llama 2 was released in July 2023.",
        "verdict": "supported",
        "confidence": 0.93,
        "probabilities": {"supported": 0.93, "contradicted": 0.02},
        "sift_steps": {"stop": {"checkable_assertion": "release date"}, "trace_claim": "Meta blog"},
        "citations": [{"url": "https://ai.meta.com/llama", "title": "Llama 2", "quote": "July 18"}],
        "parent_text": "Context paragraph.",
        "trace_id": "a" * 32,
        "model": "m + jev",
        "latency_ms": 12000,
        "sfl": {"mood": "declarative", "modality": "high"},
    },
    {
        "external_id": "d:1:1",
        "text": "Most systems use BM25.",
        "verdict": "unverifiable",
        "confidence": 0.6,
        "probabilities": {},
        "sift_steps": {},
        "citations": [],
        "parent_text": "",
        "trace_id": None,
        "model": None,
        "latency_ms": None,
        "sfl": None,
    },
]


def test_factcheck_render_columns_and_evidence(monkeypatch) -> None:
    monkeypatch.delenv("LANGFUSE_HOST", raising=False)
    monkeypatch.delenv("LANGFUSE_BASE_URL", raising=False)
    state = TUIState()
    state.mode = Mode.FACT_CHECK
    state.selected_notebook = "nb-1"
    state.factcheck_view.update(claims=CLAIMS, filter=None)
    claims, sift, evidence = render_factcheck(state)
    out = _plain(claims)
    assert "✓" in out and "supported" in out and "declarative/high" in out and "12s" in out
    assert "a/c/u" in out
    sift_out = _plain(sift)
    assert "release date" in sift_out and "supported (0.93)" in sift_out
    ev = _plain(evidence)
    assert "https://ai.meta.com/llama" in ev and "Context paragraph." in ev
    assert f"http://tinybot:3000/trace/{'a' * 32}" in ev


def test_factcheck_filter_keys(monkeypatch) -> None:
    calls: list = []
    monkeypatch.setattr(corpus_view, "load_claims", lambda s, force=False: calls.append(force))
    state = TUIState()
    state.mode = Mode.FACT_CHECK
    state.selected_notebook = "nb-1"
    handle_key("c", state)
    assert state.factcheck_view["filter"] == "contradicted"
    handle_key("u", state)
    assert state.factcheck_view["filter"] == "unverifiable"
    handle_key("a", state)
    assert state.factcheck_view["filter"] is None
    handle_key("g", state)
    assert calls == [False, False, False, True]


def test_legacy_assessment_keeps_default_layout() -> None:
    state = TUIState()
    state.mode = Mode.FACT_CHECK
    assert layout_mode(state) == Mode.FACT_CHECK
    state.assessment_state = {"chunks": []}
    assert layout_mode(state) == Mode.NOTEBOOKS
