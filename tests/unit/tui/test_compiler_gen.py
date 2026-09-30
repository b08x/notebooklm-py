"""Unit tests for the Compiler view's compile/generate workers (facts 1–14, 18–20).

The bridge, the NotebookLM client, and the LLM layer are faked throughout —
these tests never touch the network, Postgres, or an LLM.
"""

from __future__ import annotations

import contextlib
import json
import re
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

import notebooklm.tui.views.compiler_gen as gen
from notebooklm.tui.keypress import handle_key
from notebooklm.tui.state import TUIState, View

AUDIO_YAML = """\
notebook_id: yaml-notebook-id
title: "Fake Project"
topic: "fake topic"
auto_extract: false
template: mr-and-mrs-language-model
audio_format: deep-dive
audio_length: default
"""


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeLexical:
    def __init__(self) -> None:
        self.agreement = "[yaml agreement]"
        self.confusion = "[yaml confusion]"
        self.frustration = "[yaml frustration]"
        self.brainstorm = "[yaml brainstorm]"


class FakeEscalation:
    def __init__(self, compound: str = "", diagnostic: str = "", tier: str = ""):
        self.compound = compound
        self.diagnostic = diagnostic
        self.tier = tier


class FakeConfig:
    def __init__(self, auto_extract: bool = True, fmt: str = "deep-dive", length: str = "default"):
        self.notebook_id = "yaml-notebook-id"
        self.auto_extract = auto_extract
        self.audio_format = fmt
        self.audio_length = length
        self.template = "mr-and-mrs-language-model"
        self.title = "Fake Project"
        self.topic = "fake topic"
        self.lexical_dictionary = FakeLexical()
        self.topics = ["yaml topic"]
        self.escalations = [FakeEscalation("State 2 + State 3", "yaml diagnostic", "Severity 1")]


class FakeNotebooks:
    def __init__(self, title: str = "SFL Notebook") -> None:
        self._title = title

    async def get(self, notebook_id: str):
        return SimpleNamespace(id=notebook_id, title=self._title)


class FakeArtifacts:
    """Records calls and the compiler phase at each call (for phase ordering)."""

    def __init__(self, state: TUIState) -> None:
        self._state = state
        self.generate_calls: list[dict] = []
        self.download_calls: list[dict] = []
        self.fail_generate = False
        self.incomplete = False
        self.wait_calls: list[str] = []
        # Queue of statuses for successive wait_for_completion calls; when empty,
        # falls back to complete/incomplete.
        self.wait_results: list[SimpleNamespace] = []
        # Rows returned by list(): SimpleNamespace(id=..., is_failed=...).
        self.listed: list[SimpleNamespace] = []
        self.list_calls = 0

    async def generate_audio(
        self, notebook_id, instructions=None, audio_format=None, audio_length=None, **kw
    ):
        self.generate_calls.append(
            {
                "notebook_id": notebook_id,
                "instructions": instructions,
                "audio_format": audio_format,
                "audio_length": audio_length,
            }
        )
        self._log_phase()
        if self.fail_generate:
            raise RuntimeError("rate limited")
        return SimpleNamespace(task_id="art-123")

    async def wait_for_completion(self, notebook_id, task_id, **kw):
        self.wait_calls.append(task_id)
        self._log_phase()
        if self.wait_results:
            return self.wait_results.pop(0)
        return SimpleNamespace(
            is_complete=not self.incomplete,
            is_removed=False,
            status="incomplete" if self.incomplete else "complete",
        )

    async def list(self, notebook_id, **kw):
        self.list_calls += 1
        return list(self.listed)

    async def download_audio(self, notebook_id, output_path, artifact_id=None, **kw):
        self.download_calls.append(
            {"notebook_id": notebook_id, "output_path": output_path, "artifact_id": artifact_id}
        )
        self._log_phase()
        Path(output_path).write_bytes(b"ID3 fake mp3")
        return output_path

    def _log_phase(self) -> None:
        self._state.compiler_state.setdefault("phase_log", []).append(
            self._state.compiler_state.get("phase")
        )


def _patch_client(monkeypatch, state: TUIState) -> FakeArtifacts:
    artifacts = FakeArtifacts(state)

    class _Client:
        notebooks = FakeNotebooks()

    _Client.artifacts = artifacts

    class _CM:
        async def __aenter__(self):
            return _Client()

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(gen, "NotebookLMClient", SimpleNamespace(from_storage=lambda: _CM()))
    return artifacts


def _patch_session(monkeypatch) -> None:
    import notebooklm.db.session as db_session

    class _SessionCM:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(db_session, "async_session_maker", lambda: _SessionCM())


@pytest.fixture
def no_router(monkeypatch):
    """Keep the real DSPy router (litellm/Ollama) out of unit tests."""
    import notebooklm._app.assessment as assessment

    monkeypatch.setattr(assessment, "setup_dspy_router", lambda: (None, None))


def _compiled_state(**overrides) -> TUIState:
    state = TUIState()
    state.current_view = View.COMPILER
    state.selected_notebook = "nb-1"
    state.compiler_state = {
        "phase": "compiled",
        "prompt": "COMPILED PROMPT",
        "edited": False,
        "project": "sfl-engine-pipeline-mechanics",
        "project_yaml": "/x/sfl-engine-pipeline-mechanics.yaml",
        "template": "mr-and-mrs-language-model",
        "notebook_id": "nb-1",
        "notebook_title": "SFL Notebook",
        "audio_format": "deep-dive",
        "audio_length": "default",
        "evidence": {"agreement": [("c-1", "checkpoint clause text")]},
        **overrides,
    }
    return state


# ---------------------------------------------------------------------------
# to_audio_enums (fact 8, fact 14)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("fmt", "expected"),
    [
        ("deep-dive", gen.AudioFormat.DEEP_DIVE),
        ("brief", gen.AudioFormat.BRIEF),
        ("critique", gen.AudioFormat.CRITIQUE),
        ("debate", gen.AudioFormat.DEBATE),
        ("default", None),
        ("", None),
    ],
)
def test_to_audio_enums_formats(fmt, expected):
    assert gen.to_audio_enums(fmt, "default")[0] is expected


@pytest.mark.parametrize(
    ("length", "expected"),
    [
        ("short", gen.AudioLength.SHORT),
        ("default", None),
        ("long", gen.AudioLength.LONG),
        ("", None),
    ],
)
def test_to_audio_enums_lengths(length, expected):
    assert gen.to_audio_enums("deep-dive", length)[1] is expected


def test_to_audio_enums_default_maps_to_none():
    assert gen.to_audio_enums("default", "default") == (None, None)


def test_to_audio_enums_invalid_raises_with_choices():
    with pytest.raises(ValueError, match="deep-dive, brief, critique, debate"):
        gen.to_audio_enums("bogus", "default")
    with pytest.raises(ValueError, match="short, default, long"):
        gen.to_audio_enums("deep-dive", "bogus")


# ---------------------------------------------------------------------------
# start_compile / _run_compile (facts 1–3)
# ---------------------------------------------------------------------------


def test_start_compile_requires_selected_notebook(no_router):
    state = TUIState()
    gen.start_compile(state, "proj.yaml")
    assert state.compiler_state["error"] == "select a notebook first"
    assert state.compiler_task is None


def test_compile_overrides_notebook_id_and_leaves_yaml_untouched(monkeypatch, tmp_path, no_router):
    yaml_path = tmp_path / "proj.yaml"
    yaml_path.write_text(AUDIO_YAML)
    before_bytes = yaml_path.read_bytes()
    before_mtime = yaml_path.stat().st_mtime_ns

    seen: dict = {}

    async def fake_chat_fallback(client, notebook_id, config):
        seen["notebook_id"] = notebook_id
        seen["config_notebook_id"] = config.notebook_id

    monkeypatch.setattr(gen, "_chat_fallback", fake_chat_fallback)
    monkeypatch.setattr(gen, "compile_audio_config", lambda config: "COMPILED PROMPT")
    _patch_client(monkeypatch, TUIState())

    state = _compiled_state()
    state.compiler_state = {}
    state.selected_notebook = "nb-1"
    gen.start_compile(state, yaml_path)
    state.compiler_task.result()

    # The YAML's notebook_id is ignored (fact 2) and the file is untouched.
    assert seen["notebook_id"] == "nb-1"
    assert seen["config_notebook_id"] == "nb-1"
    assert yaml_path.read_bytes() == before_bytes
    assert yaml_path.stat().st_mtime_ns == before_mtime
    cs = state.compiler_state
    assert cs["phase"] == "compiled"
    assert cs["prompt"] == "COMPILED PROMPT"
    assert cs["notebook_title"] == "SFL Notebook"
    assert cs["audio_format"] == "deep-dive"
    assert cs["audio_length"] == "default"
    assert cs["edited"] is False
    assert cs["project"] == "proj"
    assert cs["template"] == "mr-and-mrs-language-model"


def test_compile_refuses_while_already_compiling(monkeypatch, no_router):
    state = _compiled_state(phase="compiling")
    gen.start_compile(state, "proj.yaml")
    assert state.compiler_task is None


def test_compile_with_auto_extract_uses_rrf_slots(monkeypatch, no_router):
    config = FakeConfig(auto_extract=True)
    monkeypatch.setattr(gen, "load_audio_project", lambda path: config)
    monkeypatch.setattr(gen, "compile_audio_config", lambda config: "COMPILED PROMPT")
    _patch_session(monkeypatch)

    calls: list[dict] = []

    async def fake_fill(client, session, notebook_id, config, lm):
        calls.append({"notebook_id": notebook_id, "lm": lm})
        return gen.SlotFill(evidence={"agreement": [("c-1", "checkpoint text")]})

    async def no_chat(client, notebook_id, config):
        raise AssertionError("chat fallback must not run when clauses are ingested")

    monkeypatch.setattr(gen, "fill_slots_from_clauses", fake_fill)
    monkeypatch.setattr(gen, "_chat_fallback", no_chat)
    _patch_client(monkeypatch, TUIState())

    state = _compiled_state()
    state.compiler_state = {}
    gen.start_compile(state, "proj.yaml")
    state.compiler_task.result()

    assert calls[0]["notebook_id"] == "nb-1"
    cs = state.compiler_state
    assert cs["evidence"] == {"agreement": [("c-1", "checkpoint text")]}
    assert cs.get("warning") is None


def test_compile_without_clauses_falls_back_to_chat_with_warning(monkeypatch, no_router):
    config = FakeConfig(auto_extract=True)
    monkeypatch.setattr(gen, "load_audio_project", lambda path: config)
    monkeypatch.setattr(gen, "compile_audio_config", lambda config: "COMPILED PROMPT")
    _patch_session(monkeypatch)

    async def no_fill(client, session, notebook_id, config, lm):
        return None

    chat_calls: list[tuple] = []

    async def fake_chat(client, notebook_id, config):
        chat_calls.append((notebook_id, config))

    monkeypatch.setattr(gen, "fill_slots_from_clauses", no_fill)
    monkeypatch.setattr(gen, "_chat_fallback", fake_chat)
    _patch_client(monkeypatch, TUIState())

    state = _compiled_state()
    state.compiler_state = {}
    gen.start_compile(state, "proj.yaml")
    state.compiler_task.result()

    assert chat_calls and chat_calls[0][0] == "nb-1"
    assert "chat fallback" in state.compiler_state["warning"]


def test_compile_extraction_failure_keeps_yaml_values_with_warning(monkeypatch, no_router):
    config = FakeConfig(auto_extract=True)
    monkeypatch.setattr(gen, "load_audio_project", lambda path: config)
    monkeypatch.setattr(gen, "compile_audio_config", lambda config: "COMPILED PROMPT")
    _patch_session(monkeypatch)

    async def exploding_fill(client, session, notebook_id, config, lm):
        raise RuntimeError("ollama down")

    async def no_chat(client, notebook_id, config):
        raise RuntimeError("chat down too")

    monkeypatch.setattr(gen, "fill_slots_from_clauses", exploding_fill)
    monkeypatch.setattr(gen, "_chat_fallback", no_chat)
    _patch_client(monkeypatch, TUIState())

    state = _compiled_state()
    state.compiler_state = {}
    gen.start_compile(state, "proj.yaml")
    state.compiler_task.result()

    cs = state.compiler_state
    assert cs["phase"] == "compiled"
    assert "Slot extraction failed" in cs["warning"]
    # The YAML's own values were kept (fact 3).
    assert config.lexical_dictionary.agreement == "[yaml agreement]"
    assert config.topics == ["yaml topic"]


def test_compile_invalid_format_shows_error(monkeypatch, no_router):
    config = FakeConfig(fmt="bogus")
    monkeypatch.setattr(gen, "load_audio_project", lambda path: config)
    _patch_client(monkeypatch, TUIState())

    state = _compiled_state()
    state.compiler_state = {}
    gen.start_compile(state, "proj.yaml")
    state.compiler_task.result()

    cs = state.compiler_state
    assert cs["phase"] == "error"
    assert "bogus" in cs["error"]


def test_worker_never_calls_setup_dspy_router_off_main_thread(monkeypatch, no_router):
    """Fact 20: the LM is captured on the main thread; the worker never reconfigures."""
    import notebooklm._app.assessment as assessment

    main_thread = threading.main_thread()

    def guarded_router():
        if threading.current_thread() is not main_thread:
            raise AssertionError("setup_dspy_router called from worker thread")
        return (None, None)

    monkeypatch.setattr(assessment, "setup_dspy_router", guarded_router)

    config = FakeConfig(auto_extract=True)
    monkeypatch.setattr(gen, "load_audio_project", lambda path: config)
    monkeypatch.setattr(gen, "compile_audio_config", lambda config: "COMPILED")
    _patch_session(monkeypatch)

    async def fake_fill(client, session, notebook_id, config, lm):
        assert lm is None  # no router in this environment — passed through, not rebuilt
        return gen.SlotFill(evidence={})

    monkeypatch.setattr(gen, "fill_slots_from_clauses", fake_fill)
    _patch_client(monkeypatch, TUIState())

    state = _compiled_state()
    state.compiler_state = {}
    gen.start_compile(state, "proj.yaml")
    state.compiler_task.result()  # raises inside the worker if fact 20 is violated
    assert state.compiler_state["phase"] == "compiled"


# ---------------------------------------------------------------------------
# fill_slots_from_clauses (facts 18–20)
# ---------------------------------------------------------------------------


def _patch_dspy_predict(monkeypatch, prediction) -> list[dict]:
    import dspy

    calls: list[dict] = []

    def fake_predict(signature):
        assert signature is gen.CompilerSlotSignature

        def call(**kwargs):
            calls.append(kwargs)
            return prediction

        return call

    monkeypatch.setattr(dspy, "Predict", fake_predict)
    monkeypatch.setattr(dspy, "context", lambda **kw: contextlib.nullcontext())
    return calls


def _patch_retrieval(monkeypatch, matches) -> None:
    import notebooklm._app.clause_search as cs

    async def fake_doc_ids(client, notebook_id):
        return ["doc-1"]

    async def fake_rrf(session, document_ids, query, top_k=8, k=60, embedder=None):
        assert document_ids == ["doc-1"]
        return list(matches)

    monkeypatch.setattr(cs, "_notebook_document_ids", fake_doc_ids)
    monkeypatch.setattr(cs, "rrf_search", fake_rrf)


def test_fill_slots_no_document_ids_returns_none(monkeypatch):
    import notebooklm._app.clause_search as cs

    async def no_docs(client, notebook_id):
        return []

    monkeypatch.setattr(cs, "_notebook_document_ids", no_docs)

    result = asyncio_run(
        gen.fill_slots_from_clauses(object(), object(), "nb-1", FakeConfig(), None)
    )
    assert result is None


def test_fill_slots_no_clauses_returns_none(monkeypatch):
    _patch_retrieval(monkeypatch, [])
    result = asyncio_run(
        gen.fill_slots_from_clauses(object(), object(), "nb-1", FakeConfig(), None)
    )
    assert result is None


def test_fill_slots_writes_slots_and_evidence(monkeypatch):
    from notebooklm._app.clause_search import MatchedClause

    matches = [
        MatchedClause(clause_id="c-1", document_id="doc-1", text="First checkpoint clause."),
        MatchedClause(clause_id="c-2", document_id="doc-1", text="Second desync clause."),
    ]
    _patch_retrieval(monkeypatch, matches)
    prediction = SimpleNamespace(
        agreement="Pass 1 structural checkpoint confirmed",
        confusion="Pass 2 tagging desync",
        frustration="RRF fusion starvation",
        brainstorm="Unconstrained tenor speculation",
        topics="Mechanism 1: the two-pass pipeline\nMechanism 2: dual payloads\nMechanism 3: hybrid retrieval",
        escalations="State 2 + State 3 :: merge junction stalls :: Severity 1 (Fatal)",
        citations="agreement: C2; confusion: C1; frustration: C1; brainstorm: C2; topics: C1, C2; escalations: C2",
    )
    calls = _patch_dspy_predict(monkeypatch, prediction)

    config = FakeConfig()
    result = asyncio_run(gen.fill_slots_from_clauses(object(), object(), "nb-1", config, "fake-lm"))

    assert calls[0]["topic"] == "fake topic"
    assert "[C1] First checkpoint clause." in calls[0]["context"]
    assert "[C2] Second desync clause." in calls[0]["context"]

    assert config.lexical_dictionary.agreement == "[Pass 1 structural checkpoint confirmed]"
    assert config.lexical_dictionary.confusion == "[Pass 2 tagging desync]"
    assert config.lexical_dictionary.frustration == "[RRF fusion starvation]"
    assert config.lexical_dictionary.brainstorm == "[Unconstrained tenor speculation]"
    assert config.topics == [
        "Mechanism 1: the two-pass pipeline",
        "Mechanism 2: dual payloads",
        "Mechanism 3: hybrid retrieval",
    ]
    assert len(config.escalations) == 1
    assert config.escalations[0].diagnostic == "merge junction stalls"

    assert result.evidence["agreement"] == [("c-2", "Second desync clause.")]
    assert result.evidence["confusion"] == [("c-1", "First checkpoint clause.")]
    assert result.evidence["topics"] == [
        ("c-1", "First checkpoint clause."),
        ("c-2", "Second desync clause."),
    ]


def test_fill_slots_wraps_values_in_brackets_once(monkeypatch):
    assert gen._wrap_slot("State 1: checkpoint") == "[State 1: checkpoint]"
    assert gen._wrap_slot("[State 1: checkpoint]") == "[State 1: checkpoint]"


def asyncio_run(coro):
    import asyncio

    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# $EDITOR handoff (fact 6)
# ---------------------------------------------------------------------------


def _fake_run(new_text: str | None, returncode: int = 0, *, raises: bool = False):
    def run(cmd, **kw):
        if raises:
            raise FileNotFoundError(cmd[0])
        if new_text is not None:
            Path(cmd[1]).write_text(new_text, encoding="utf-8")
        return SimpleNamespace(returncode=returncode)

    return run


def test_edit_prompt_changed(monkeypatch):
    monkeypatch.setenv("EDITOR", "myed")
    result = gen.edit_prompt_via_editor("ORIGINAL", run=_fake_run("EDITED"))
    assert result.edited is True
    assert result.text == "EDITED"
    assert result.error is None


def test_edit_prompt_unchanged(monkeypatch):
    monkeypatch.setenv("EDITOR", "myed")
    result = gen.edit_prompt_via_editor("ORIGINAL", run=_fake_run("ORIGINAL"))
    assert result.edited is False
    assert result.text == "ORIGINAL"


def test_edit_prompt_nonzero_exit_keeps_original(monkeypatch):
    monkeypatch.setenv("EDITOR", "myed")
    result = gen.edit_prompt_via_editor("ORIGINAL", run=_fake_run("EDITED", returncode=1))
    assert result.edited is False
    assert result.text == "ORIGINAL"
    assert result.error is not None


def test_edit_prompt_missing_editor(monkeypatch):
    monkeypatch.setenv("EDITOR", "nonexistent-editor")
    result = gen.edit_prompt_via_editor("ORIGINAL", run=_fake_run(None, raises=True))
    assert result.edited is False
    assert result.text == "ORIGINAL"
    assert "not found" in result.error


def test_editor_falls_back_to_vim_then_vi(monkeypatch):
    monkeypatch.delenv("EDITOR", raising=False)
    seen: list[str] = []

    def run(cmd, **kw):
        seen.append(cmd[0])
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(
        gen.shutil, "which", lambda name: "/usr/bin/nvim" if name == "nvim" else None
    )
    gen.edit_prompt_via_editor("x", run=run)
    assert seen == ["/usr/bin/nvim"]


def test_apply_editor_result_marks_edited_and_never_touches_yaml():
    state = _compiled_state(edited=False)
    gen.apply_editor_result(state, gen.EditorResult(text="EDITED PROMPT", edited=True))
    cs = state.compiler_state
    assert cs["prompt"] == "EDITED PROMPT"
    assert cs["edited"] is True
    assert cs["scroll"] == 0

    gen.apply_editor_result(state, gen.EditorResult(text="kept", edited=False, error="boom"))
    assert cs["prompt"] == "EDITED PROMPT"
    assert cs["error"] == "boom"


# ---------------------------------------------------------------------------
# Generate worker (facts 7–12)
# ---------------------------------------------------------------------------


def test_generate_sends_exact_prompt_enums_and_writes_mp3_and_sidecar(
    monkeypatch, tmp_path, no_router
):
    state = _compiled_state(prompt="EDITED PROMPT", edited=True, audio_length="long")
    artifacts = _patch_client(monkeypatch, state)
    monkeypatch.setenv("NOTEBOOKLM_AUDIO_DIR", str(tmp_path))

    gen.start_generate(state)
    state.compiler_task.result()

    # The instructions argument equals the edited prompt byte for byte (fact 8).
    assert artifacts.generate_calls[0]["instructions"] == "EDITED PROMPT"
    assert artifacts.generate_calls[0]["audio_format"] is gen.AudioFormat.DEEP_DIVE
    assert artifacts.generate_calls[0]["audio_length"] is gen.AudioLength.LONG

    # Phases occur in order (fact 9): submitted → generating → downloading.
    assert state.compiler_state["phase_log"] == ["submitted", "generating", "downloading"]
    assert state.compiler_state["phase"] == "done"

    # MP3 path pattern: <project-slug>/<YYYYMMDD-HHMM>_<notebook-slug>.mp3 (fact 10).
    mp3 = Path(state.compiler_state["mp3_path"])
    assert mp3.exists() and mp3.read_bytes() == b"ID3 fake mp3"
    assert mp3.parent == tmp_path / "sfl-engine-pipeline-mechanics"
    assert re.fullmatch(r"\d{8}-\d{4}_sfl-notebook\.mp3", mp3.name)

    # Sidecar (fact 11): every field, next to the MP3.
    sidecar = mp3.with_suffix(".json")
    assert sidecar == Path(state.compiler_state["sidecar_path"])
    data = json.loads(sidecar.read_text())
    assert data["project_yaml"] == "/x/sfl-engine-pipeline-mechanics.yaml"
    assert data["template"] == "mr-and-mrs-language-model"
    assert data["notebook_id"] == "nb-1"
    assert data["notebook_title"] == "SFL Notebook"
    assert data["artifact_id"] == "art-123"
    assert data["audio_format"] == "deep-dive"
    assert data["audio_length"] == "long"
    assert data["prompt"] == "EDITED PROMPT"
    assert data["edited"] is True
    assert data["slot_evidence"] == {
        "agreement": [{"clause_id": "c-1", "text": "checkpoint clause text"}]
    }
    assert data["status"] == "done"
    assert data["error"] is None
    assert data["started_at"] and data["finished_at"]


def test_generate_failure_writes_sidecar_and_keeps_prompt_for_retry(
    monkeypatch, tmp_path, no_router
):
    state = _compiled_state(prompt="EDITED PROMPT", edited=True)
    artifacts = _patch_client(monkeypatch, state)
    artifacts.fail_generate = True
    monkeypatch.setenv("NOTEBOOKLM_AUDIO_DIR", str(tmp_path))

    gen.start_generate(state)
    state.compiler_task.result()

    cs = state.compiler_state
    assert cs["phase"] == "failed"
    assert "rate limited" in cs["error"]
    # The prompt, including edits, is kept so `g` retries (fact 12).
    assert cs["prompt"] == "EDITED PROMPT"
    assert cs["edited"] is True
    assert cs.get("mp3_path") is None

    sidecar = Path(cs["sidecar_path"])
    data = json.loads(sidecar.read_text())
    assert data["status"] == "failed"
    assert "rate limited" in data["error"]
    assert data["prompt"] == "EDITED PROMPT"
    assert data["edited"] is True


def test_generate_incomplete_status_fails(monkeypatch, tmp_path, no_router):
    state = _compiled_state()
    artifacts = _patch_client(monkeypatch, state)
    artifacts.incomplete = True
    monkeypatch.setenv("NOTEBOOKLM_AUDIO_DIR", str(tmp_path))

    gen.start_generate(state)
    state.compiler_task.result()

    cs = state.compiler_state
    assert cs["phase"] == "failed"
    assert "did not complete" in cs["error"]
    assert cs["artifact_id"] == "art-123"


_REMOVED = SimpleNamespace(is_complete=False, is_removed=True, status="removed")
_COMPLETE = SimpleNamespace(is_complete=True, is_removed=False, status="complete")


def test_generate_removed_but_still_listed_keeps_waiting(monkeypatch, tmp_path, no_router):
    """A "removed" poll result for an artifact that is still in the listing is a
    transient omission: keep waiting and download it instead of failing."""
    state = _compiled_state()
    artifacts = _patch_client(monkeypatch, state)
    artifacts.wait_results = [_REMOVED, _COMPLETE]
    artifacts.listed = [SimpleNamespace(id="art-123", is_failed=False)]
    monkeypatch.setenv("NOTEBOOKLM_AUDIO_DIR", str(tmp_path))

    gen.start_generate(state)
    state.compiler_task.result()

    cs = state.compiler_state
    assert cs["phase"] == "done"
    assert len(artifacts.generate_calls) == 1
    assert artifacts.wait_calls == ["art-123", "art-123"]
    assert artifacts.download_calls[0]["artifact_id"] == "art-123"


def test_generate_removed_and_gone_fails(monkeypatch, tmp_path, no_router):
    state = _compiled_state()
    artifacts = _patch_client(monkeypatch, state)
    artifacts.wait_results = [_REMOVED]
    artifacts.listed = []
    monkeypatch.setenv("NOTEBOOKLM_AUDIO_DIR", str(tmp_path))

    gen.start_generate(state)
    state.compiler_task.result()

    cs = state.compiler_state
    assert cs["phase"] == "failed"
    assert "removed" in cs["error"]
    assert artifacts.wait_calls == ["art-123"]
    assert cs["artifact_id"] == "art-123"


def test_retry_after_failure_resumes_existing_artifact(monkeypatch, tmp_path, no_router):
    """Pressing g after a failure whose artifact still exists resumes that
    artifact (wait + download) instead of starting a new generation."""
    state = _compiled_state(phase="failed", artifact_id="art-9", error="removed")
    artifacts = _patch_client(monkeypatch, state)
    artifacts.listed = [SimpleNamespace(id="art-9", is_failed=False)]
    monkeypatch.setenv("NOTEBOOKLM_AUDIO_DIR", str(tmp_path))

    gen.start_generate(state)
    state.compiler_task.result()

    cs = state.compiler_state
    assert artifacts.generate_calls == []
    assert artifacts.wait_calls == ["art-9"]
    assert artifacts.download_calls[0]["artifact_id"] == "art-9"
    assert cs["phase"] == "done"
    data = json.loads(Path(cs["sidecar_path"]).read_text())
    assert data["artifact_id"] == "art-9"


def test_retry_after_failed_artifact_regenerates(monkeypatch, tmp_path, no_router):
    """A server-FAILED or vanished artifact is not resumed; g generates anew."""
    state = _compiled_state(phase="failed", artifact_id="art-9", error="failed")
    artifacts = _patch_client(monkeypatch, state)
    artifacts.listed = [SimpleNamespace(id="art-9", is_failed=True)]
    monkeypatch.setenv("NOTEBOOKLM_AUDIO_DIR", str(tmp_path))

    gen.start_generate(state)
    state.compiler_task.result()

    assert len(artifacts.generate_calls) == 1
    assert artifacts.wait_calls == ["art-123"]
    assert state.compiler_state["phase"] == "done"


def test_start_generate_does_nothing_while_running(no_router):
    state = _compiled_state(phase="generating")
    gen.start_generate(state)
    assert state.compiler_task is None


def test_start_generate_requires_prompt(no_router):
    state = _compiled_state()
    del state.compiler_state["prompt"]
    gen.start_generate(state)
    assert state.compiler_task is None


# ---------------------------------------------------------------------------
# Confirm panel keys (fact 7)
# ---------------------------------------------------------------------------


def test_confirm_keys_send_and_cancel(monkeypatch, no_router):
    started: list[TUIState] = []

    def fake_start(state):
        started.append(state)
        state.compiler_state["confirm"] = False

    monkeypatch.setattr(gen, "start_generate", fake_start)

    state = _compiled_state()

    # g opens the confirmation panel.
    handle_key("g", state)
    assert state.compiler_state["confirm"] is True

    # y sends exactly once.
    handle_key("y", state)
    assert started and started[0] is state
    assert state.compiler_state["confirm"] is False


def test_confirm_cancel_makes_no_request(monkeypatch, no_router):
    """`n` and Escape cancel without any client call (fact 7)."""
    calls: list = []
    monkeypatch.setattr(gen, "start_generate", lambda state: calls.append(state))

    for cancel_key in ("n", "\x1b"):
        state = _compiled_state()
        handle_key("g", state)
        assert state.compiler_state["confirm"] is True
        handle_key(cancel_key, state)
        assert state.compiler_state.get("confirm") is False
        assert calls == []
        assert state.compiler_task is None


def test_g_and_e_require_a_compiled_prompt(no_router):
    state = _compiled_state()
    state.compiler_state = {"configs": [Path("a.yaml")], "selected_config": 0}
    state.compiler_state["phase"] = "compiled"

    handle_key("g", state)
    assert state.compiler_state.get("confirm") is None
    handle_key("e", state)
    assert state.compiler_state.get("edit_requested") is None


def test_g_and_e_blocked_while_generating(no_router):
    state = _compiled_state(phase="generating")
    handle_key("g", state)
    assert state.compiler_state.get("confirm") is None
    handle_key("e", state)
    assert state.compiler_state.get("edit_requested") is None


def test_e_requests_editor_and_enter_recompiles(monkeypatch):
    recompiled: list = []
    monkeypatch.setattr(gen, "start_compile", lambda state, path: recompiled.append(path))

    state = _compiled_state()
    handle_key("e", state)
    assert state.compiler_state["edit_requested"] is True

    state.compiler_state["configs"] = [Path("/examples/x.yaml")]
    state.compiler_state["selected_config"] = 0
    handle_key("\r", state)
    assert recompiled == [Path("/examples/x.yaml")]


def test_jk_scrolls_preview_when_compiled():
    state = _compiled_state()
    handle_key("j", state)
    assert state.compiler_state["scroll"] == 1
    handle_key("j", state)
    assert state.compiler_state["scroll"] == 2
    handle_key("k", state)
    assert state.compiler_state["scroll"] == 1
    handle_key("k", state)
    handle_key("k", state)
    assert state.compiler_state["scroll"] == 0


def test_jk_moves_config_selection_without_prompt():
    state = TUIState()
    state.current_view = View.COMPILER
    state.compiler_state = {"configs": [Path("a.yaml"), Path("b.yaml")], "selected_config": 0}
    handle_key("j", state)
    assert state.compiler_state["selected_config"] == 1
    handle_key("k", state)
    assert state.compiler_state["selected_config"] == 0
    assert "scroll" not in state.compiler_state


def test_video_yaml_keeps_preview_only(monkeypatch):
    from notebooklm.tui import compiler_bridge
    from notebooklm.tui.views import compiler_view

    audio_compiled: list = []
    monkeypatch.setattr(gen, "start_compile", lambda state, path: audio_compiled.append(path))
    monkeypatch.setattr(
        compiler_bridge,
        "compile_video_project",
        lambda path: SimpleNamespace(style_prompt="STYLE", instructions="INSTRUCTIONS"),
    )

    state = _compiled_state()
    state.compiler_state = {
        "configs": [Path("/examples/notebooklm-video/projects/v.yaml")],
        "selected_config": 0,
    }
    compiler_view.compile_selected(state)
    assert "Video Prompt:" in state.compiler_state["preview"]
    assert audio_compiled == []

    # And the audio YAML delegates to start_compile (facts 1–2).
    state.compiler_state["configs"] = [Path("/examples/notebooklm-audio/projects/a.yaml")]
    compiler_view.compile_selected(state)
    assert audio_compiled == [Path("/examples/notebooklm-audio/projects/a.yaml")]


# ---------------------------------------------------------------------------
# Output path (fact 10)
# ---------------------------------------------------------------------------


def test_audio_output_base_pattern(tmp_path):
    from datetime import datetime

    base = gen.audio_output_base(
        "SFL Engine: Pipeline Mechanics!",
        "SFL Notebook",
        now=datetime(2026, 9, 29, 14, 5),
        audio_dir=str(tmp_path),
    )
    assert base == tmp_path / "sfl-engine-pipeline-mechanics" / "20260929-1405_sfl-notebook"
