"""compile and generate job handlers: phases mirror into compiler_state and the job store."""

from __future__ import annotations

import time
from pathlib import Path
from types import SimpleNamespace

import pytest

import notebooklm.tui.views.compiler_gen as gen
from notebooklm.tui.jobs.handlers import compile as compile_handler
from notebooklm.tui.jobs.handlers import generate as generate_handler
from notebooklm.tui.jobs.runner import JobRunner
from notebooklm.tui.jobs.store import Job, JobStatus
from notebooklm.tui.state import TUIState, View


def _state(**compiler_state) -> TUIState:
    state = TUIState()
    state.current_view = View.COMPILER
    state.selected_notebook = "nb-1"
    state.compiler_state = {"phase": "compiling", **compiler_state}
    return state


def _runner(store, state, handlers) -> JobRunner:
    return JobRunner(store, handlers, state=state, workers=1)


def _run_queued(store, state, kind: str, handlers: dict) -> Job:
    """Claim the queued job of ``kind`` and run it through the real runner."""
    job = store.claim()
    assert job is not None and job.kind == kind
    _runner(store, state, handlers).run_job(job)
    finished = store.get(job.id)
    assert finished is not None
    return finished


# ---------------------------------------------------------------------------
# compile
# ---------------------------------------------------------------------------


def test_compile_job_mirrors_phases_with_injected_compile(store):
    state = _state()
    seen: list[tuple[Path, str]] = []

    async def fake_compile(st, project_file, notebook_id, lm, *, progress, before_api):
        seen.append((project_file, notebook_id))
        progress("compiling")
        st.compiler_state["phase"] = "compiled"
        progress("compiled")

    async def handler(ctx):
        return await compile_handler.run_compile_job(ctx, compile_fn=fake_compile)

    store.enqueue("compile", "nb-1", {"project_file": "/x/proj.yaml"})
    job = _run_queued(store, state, "compile", {"compile": handler})

    assert job.status == JobStatus.DONE
    assert job.phase == "compiled"
    assert job.summary == "compiled proj (no warnings)"
    assert state.compiler_state["phase"] == "compiled"
    assert seen == [(Path("/x/proj.yaml"), "nb-1")]


def test_compile_job_failure_fails_job_and_keeps_error_state(store):
    state = _state()

    async def boom(st, project_file, notebook_id, lm, *, progress, before_api):
        st.compiler_state.update(phase="error", error="bad yaml")
        progress("error")
        raise RuntimeError("bad yaml")

    async def handler(ctx):
        return await compile_handler.run_compile_job(ctx, compile_fn=boom)

    store.enqueue("compile", "nb-1", {"project_file": "proj.yaml"})
    job = _run_queued(store, state, "compile", {"compile": handler})

    assert job.status == JobStatus.FAILED
    assert job.error == "RuntimeError: bad yaml"
    assert job.phase == "error"
    assert state.compiler_state["error"] == "bad yaml"


def test_compile_job_requires_tui_state(store):
    store.enqueue("compile", "nb-1", {"project_file": "proj.yaml"})
    job = store.claim()
    assert job is not None
    JobRunner(store, {"compile": compile_handler.handle}, workers=1).run_job(job)

    finished = store.get(job.id)
    assert finished is not None
    assert finished.status == JobStatus.FAILED
    assert finished.error == "RuntimeError: compile job requires TUI state"


class _Notebook:
    title = "SFL Notebook"


class _Notebooks:
    async def get(self, notebook_id):
        return _Notebook()


class _Client:
    notebooks = _Notebooks()


class _ClientCM:
    async def __aenter__(self):
        return _Client()

    async def __aexit__(self, *exc):
        return False


class _SessionCM:
    async def __aenter__(self):
        return object()

    async def __aexit__(self, *exc):
        return False


def test_compile_job_real_path_updates_compiler_state(monkeypatch, store):
    import notebooklm.db.session as db_session

    config = SimpleNamespace(
        topic="SFL",
        title="SFL",
        template="mr-and-mrs-language-model",
        audio_format="deep-dive",
        audio_length="default",
        auto_extract=True,
        notebook_id="",
    )

    async def fake_fill(client, session, notebook_id, cfg, lm):
        return gen.SlotFill(evidence={"agreement": [("c-1", "checkpoint clause")]})

    monkeypatch.setattr(gen, "load_audio_project", lambda path: config)
    monkeypatch.setattr(gen, "compile_audio_config", lambda cfg: "COMPILED PROMPT")
    monkeypatch.setattr(gen, "NotebookLMClient", SimpleNamespace(from_storage=_ClientCM))
    monkeypatch.setattr(gen, "fill_slots_from_clauses", fake_fill)
    monkeypatch.setattr(db_session, "async_session_maker", _SessionCM)

    state = _state(evidence={})
    store.enqueue("compile", "nb-1", {"project_file": "/x/sfl.yaml"})
    job = _run_queued(store, state, "compile", {"compile": compile_handler.handle})

    assert job.status == JobStatus.DONE
    assert job.phase == "compiled"
    cs = state.compiler_state
    assert cs["phase"] == "compiled"
    assert cs["prompt"] == "COMPILED PROMPT"
    assert cs["notebook_title"] == "SFL Notebook"
    assert cs["project"] == "sfl"
    assert cs["evidence"] == {"agreement": [("c-1", "checkpoint clause")]}
    assert config.notebook_id == "nb-1"


# ---------------------------------------------------------------------------
# generate
# ---------------------------------------------------------------------------


def _generate_payload(tmp_path: Path, **overrides) -> dict:
    payload = {
        "notebook_id": "nb-1",
        "notebook_title": "SFL Notebook",
        "prompt": "PROMPT",
        "edited": False,
        "project_yaml": "/x/sfl.yaml",
        "project": "sfl",
        "template": "mr-and-mrs-language-model",
        "audio_format": None,
        "audio_length": None,
        "evidence": {},
        "output_base": str(tmp_path / "out"),
        "started_at": time.time(),
        "resume_artifact_id": None,
    }
    payload.update(overrides)
    return payload


def test_generate_job_mirrors_phases_with_injected_generate(store):
    state = _state(phase="submitted", mp3_path=None)

    async def fake_generate(st, payload, *, progress, before_api):
        assert payload["prompt"] == "PROMPT"
        progress("generating")
        progress("downloading")
        st.compiler_state.update(phase="done", mp3_path="/x/out.mp3")
        progress("done")

    async def handler(ctx):
        return await generate_handler.run_generate_job(ctx, generate_fn=fake_generate)

    store.enqueue("generate", "nb-1", {"prompt": "PROMPT"})
    job = _run_queued(store, state, "generate", {"generate": handler})

    assert job.status == JobStatus.DONE
    assert job.phase == "done"
    assert job.summary == "audio saved to /x/out.mp3"
    assert state.compiler_state["phase"] == "done"


def test_generate_job_requires_tui_state(store):
    store.enqueue("generate", "nb-1", {"prompt": "PROMPT"})
    job = store.claim()
    assert job is not None
    JobRunner(store, {"generate": generate_handler.handle}, workers=1).run_job(job)

    finished = store.get(job.id)
    assert finished is not None
    assert finished.status == JobStatus.FAILED
    assert finished.error == "RuntimeError: generate job requires TUI state"


def test_generate_job_failure_writes_sidecar_and_fails_job(monkeypatch, tmp_path, store):
    class _Artifacts:
        async def generate_audio(self, **kwargs):
            raise RuntimeError("quota exceeded")

    class _GenClient:
        artifacts = _Artifacts()

    class _GenCM:
        async def __aenter__(self):
            return _GenClient()

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(gen, "NotebookLMClient", SimpleNamespace(from_storage=_GenCM))
    state = _state(phase="submitted", prompt="PROMPT")

    store.enqueue("generate", "nb-1", _generate_payload(tmp_path))
    job = _run_queued(store, state, "generate", {"generate": generate_handler.handle})

    assert job.status == JobStatus.FAILED
    assert job.error == "RuntimeError: quota exceeded"
    assert job.phase == "failed"
    assert state.compiler_state["phase"] == "failed"
    assert state.compiler_state["error"] == "quota exceeded"
    sidecar = Path(state.compiler_state["sidecar_path"])
    assert sidecar.exists()
    assert sidecar.suffix == ".json"


@pytest.mark.parametrize("kind", ["compile", "generate"])
def test_handlers_registered_by_kind_name(kind):
    from notebooklm.tui.jobs.kinds import resolve_handler

    assert callable(resolve_handler(kind))
