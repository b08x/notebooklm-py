import io

from rich.console import Console, RenderableType

from notebooklm.tui.jobs.store import ItemStatus, Job, JobItem, JobStatus
from notebooklm.tui.renderers.jobs import render_jobs
from notebooklm.tui.state import TUIState
from notebooklm.tui.theme import THEME


class FakeStore:
    """Stands in for JobStore: only ``items`` is read by the renderer."""

    def __init__(self, items: dict[str, list[JobItem]]) -> None:
        self._items = items

    def items(self, job_id: str) -> list[JobItem]:
        return self._items.get(job_id, [])


def _plain(renderable: RenderableType) -> str:
    console = Console(file=io.StringIO(), width=140, color_system=None, theme=THEME)
    console.print(renderable)
    return console.file.getvalue()


def test_detail_shows_failed_item_error() -> None:
    job = Job(id="j1", kind="ingest", status=JobStatus.FAILED, error="ingest stopped")
    state = TUIState()
    state.jobs_snapshot = [job]
    state.job_store = FakeStore(
        {
            "j1": [
                JobItem(
                    id="i1",
                    name="report.pdf",
                    status=ItemStatus.FAILED,
                    error="HTTP 500 from upload",
                )
            ]
        }
    )

    _, detail = render_jobs(state)
    text = _plain(detail)

    assert "report.pdf" in text
    assert "HTTP 500 from upload" in text
    assert "ingest stopped" in text


def test_detail_shows_trace_url() -> None:
    job = Job(id="j2", kind="download", status=JobStatus.DONE, trace_id="trace123")
    state = TUIState()
    state.jobs_snapshot = [job]

    _, detail = render_jobs(state)

    assert "/trace/trace123" in _plain(detail)


def test_list_respects_status_filter() -> None:
    state = TUIState()
    state.jobs_snapshot = [
        Job(id="r1", kind="download", status=JobStatus.RUNNING, notebook_id="nbrun"),
        Job(id="d1", kind="download", status=JobStatus.DONE, notebook_id="nbdone"),
    ]
    state.jobs_view = {"status": JobStatus.DONE}

    listing, _ = render_jobs(state)
    text = _plain(listing)

    assert "nbdone" in text
    assert "nbrun" not in text
    assert "filter done" in text


def test_list_shows_percent_and_phase() -> None:
    state = TUIState()
    state.jobs_snapshot = [
        Job(
            id="p1",
            kind="ingest",
            status=JobStatus.RUNNING,
            notebook_id="nb9",
            percent=50.0,
            phase="Uploading",
        )
    ]

    listing, _ = render_jobs(state)
    text = _plain(listing)

    assert " 50%" in text
    assert "Uploading" in text


def test_empty_filter_result_shows_message() -> None:
    state = TUIState()
    state.jobs_snapshot = [Job(id="x", kind="download", status=JobStatus.RUNNING)]
    state.jobs_view = {"status": JobStatus.FAILED}

    _, detail = render_jobs(state)

    assert "No jobs match the filter." in _plain(detail)
