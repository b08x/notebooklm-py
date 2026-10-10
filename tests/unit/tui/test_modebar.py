from notebooklm.tui.jobs.store import Job, JobStatus
from notebooklm.tui.layout import build_layout
from notebooklm.tui.renderers.modebar import render_modebar
from notebooklm.tui.state import Mode, TUIState


def _job(job_id: str, status: JobStatus = JobStatus.RUNNING) -> Job:
    return Job(id=job_id, kind="download", status=status, notebook_id="nb1")


def _bar_text(state: TUIState) -> str:
    return render_modebar(state).renderable.plain


def test_modebar_lists_all_modes() -> None:
    assert "1 Notebooks │ 2 Ingest │ 3 Fact-check │ 4 Compiler │ 5 Jobs │ 6 Logs" in _bar_text(
        TUIState()
    )


def test_modebar_jobs_label_shows_running_count() -> None:
    state = TUIState()
    state.jobs_snapshot = [_job("a"), _job("b"), _job("c", JobStatus.DONE)]
    assert "Jobs (2▸)" in _bar_text(state)


def test_modebar_jobs_label_plain_when_nothing_running() -> None:
    state = TUIState()
    state.jobs_snapshot = [_job("a", JobStatus.DONE)]
    text = _bar_text(state)
    assert "5 Jobs │" in text
    assert "Jobs (" not in text


def test_every_layout_has_modebar() -> None:
    for mode in Mode:
        assert build_layout(mode).get("modebar") is not None


def test_jobs_layout_has_no_sidebar_slot() -> None:
    layout = build_layout(Mode.JOBS)
    assert layout.get("sidebar") is None
    assert layout.get("jobs_list") is not None
    assert layout.get("jobs_detail") is not None


def test_other_layouts_keep_sidebar_and_content() -> None:
    for mode in Mode:
        if mode == Mode.JOBS:
            continue
        layout = build_layout(mode)
        assert layout.get("sidebar") is not None
        assert layout.get("results") is not None
        assert layout.get("detail") is not None
