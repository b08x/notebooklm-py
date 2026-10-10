"""Tests for the ``download`` job handler and the view that enqueues it."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

from notebooklm.db.models import LocalAsset
from notebooklm.tui.jobs.handlers.download import download_notebook_assets
from notebooklm.tui.jobs.runner import JobContext, JobRunner
from notebooklm.tui.jobs.store import ItemStatus, JobStatus, JobStore
from notebooklm.tui.state import TUIState
from notebooklm.tui.views.notebook_detail import start_download


class FakeSources:
    def __init__(self, sources: list[SimpleNamespace]) -> None:
        self._sources = sources
        self.fulltext_calls: list[str] = []

    async def list(self, notebook_id: str) -> list[SimpleNamespace]:
        return self._sources

    async def get_fulltext(self, notebook_id: str, source_id: str, output_format: str) -> Any:
        self.fulltext_calls.append(source_id)
        return SimpleNamespace(content=f"# {source_id}\nbody")


class FakeChat:
    async def get_history(self, notebook_id: str) -> list[tuple[str, str]]:
        return [("hi", "hello")]


class FakeArtifacts:
    def __init__(self, artifacts: list[SimpleNamespace], failing_kind: str | None = None) -> None:
        self._artifacts = artifacts
        self._failing_kind = failing_kind
        self.download_calls: list[str] = []

    async def list(self, notebook_id: str) -> list[SimpleNamespace]:
        return self._artifacts

    async def _write(self, kind: str, output_path: str, artifact_id: str) -> None:
        self.download_calls.append(artifact_id)
        if kind == self._failing_kind:
            raise RuntimeError(f"{kind} quota exceeded")
        Path(output_path).write_text(f"{artifact_id} body")

    async def download_report(self, notebook_id: str, output_path: str, artifact_id: str) -> None:
        await self._write("report", output_path, artifact_id)

    async def download_audio(self, notebook_id: str, output_path: str, artifact_id: str) -> None:
        await self._write("audio", output_path, artifact_id)


class FakeClient:
    def __init__(
        self,
        sources: list[SimpleNamespace],
        artifacts: list[SimpleNamespace],
        *,
        failing_kind: str | None = None,
    ) -> None:
        self.notebooks = SimpleNamespace(get=self._get_notebook)
        self.sources = FakeSources(sources)
        self.chat = FakeChat()
        self.artifacts = FakeArtifacts(artifacts, failing_kind)

    async def _get_notebook(self, notebook_id: str) -> SimpleNamespace:
        return SimpleNamespace(title="Research: Notes")

    async def __aenter__(self) -> FakeClient:
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False


class FakeSession:
    """Stands in for an AsyncSession. Rows are keyed by asset_id."""

    def __init__(self, rows: dict[str, LocalAsset] | None = None) -> None:
        self.rows: dict[str, LocalAsset] = dict(rows or {})
        self.commits = 0

    async def execute(self, stmt: Any) -> SimpleNamespace:
        asset_id = next(iter(stmt.compile().params.values()))
        row = self.rows.get(asset_id)
        return SimpleNamespace(scalar_one_or_none=lambda: row)

    def add(self, obj: LocalAsset) -> None:
        self.rows[obj.asset_id] = obj

    async def commit(self) -> None:
        self.commits += 1

    async def __aenter__(self) -> FakeSession:
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False


def _sources() -> list[SimpleNamespace]:
    return [SimpleNamespace(id="src-1", title="Paper A"), SimpleNamespace(id="src-2", title="B")]


def _artifacts() -> list[SimpleNamespace]:
    return [
        SimpleNamespace(id="art-1", title="Summary", kind=SimpleNamespace(value="report")),
        SimpleNamespace(id="art-2", title="Overview", kind=SimpleNamespace(value="audio")),
    ]


def _run_download(
    store: JobStore,
    notebook_id: str,
    out_root: Path,
    client: FakeClient,
    session: FakeSession,
) -> str:
    """Run one download job through the real runner and return its job id."""

    async def handle(ctx: JobContext) -> str:
        return await download_notebook_assets(
            ctx,
            notebook_id,
            out_root=out_root,
            client_factory=lambda: client,
            session_factory=lambda: session,
        )

    job_id = store.enqueue("download", notebook_id)
    JobRunner(store, {"download": handle}).run_job(store.claim())  # type: ignore[arg-type]
    return job_id


def test_start_download_queues_one_job_per_notebook(store: JobStore) -> None:
    state = TUIState()
    state.job_store = store
    state.download_dir = "/data/out"
    state.notebooks = [SimpleNamespace(id="nb-1", title="Alpha")]

    for nb_id in ("nb-1", "nb-2", "nb-3"):
        state.selected_notebook = nb_id
        start_download(state)

    jobs = store.list_jobs(kind="download", status=JobStatus.QUEUED)
    assert sorted(j.notebook_id for j in jobs) == ["nb-1", "nb-2", "nb-3"]
    assert all(j.payload == {"download_dir": "/data/out"} for j in jobs)
    assert state.error_message == "Queued download for nb-3"


def test_start_download_message_uses_title(store: JobStore) -> None:
    state = TUIState()
    state.job_store = store
    state.selected_notebook = "nb-1"
    state.notebooks = [SimpleNamespace(id="nb-1", title="Alpha")]

    start_download(state)

    assert state.error_message == "Queued download for Alpha"


def test_start_download_noop_without_selection(store: JobStore) -> None:
    state = TUIState()
    state.job_store = store

    start_download(state)

    assert store.list_jobs(kind="download") == []


def test_failed_artifact_is_failed_item_and_job_completes(store: JobStore, tmp_path: Path) -> None:
    client = FakeClient(_sources(), _artifacts(), failing_kind="audio")
    session = FakeSession()

    job_id = _run_download(store, "nb-1", tmp_path, client, session)

    job = store.get(job_id)
    assert job is not None
    assert job.status == JobStatus.DONE
    assert job.summary and job.summary.startswith("Assets downloaded to ")

    items = {i.name: i for i in store.items(job_id)}
    assert items["Summary"].status == ItemStatus.DONE
    assert items["Summary"].bytes and items["Summary"].bytes > 0
    assert items["Overview"].status == ItemStatus.FAILED
    assert items["Overview"].error == "audio quota exceeded"
    assert items["Paper A"].status == ItemStatus.DONE
    assert items["B"].status == ItemStatus.DONE

    assert "art-2" not in session.rows
    assert {"src-1", "src-2", "art-1"} <= set(session.rows)


def test_second_run_skips_recorded_assets(store: JobStore, tmp_path: Path) -> None:
    first_client = FakeClient(_sources(), _artifacts())
    first_session = FakeSession()
    _run_download(store, "nb-1", tmp_path, first_client, first_session)
    assert len(first_session.rows) == 4

    second_client = FakeClient(_sources(), _artifacts())
    second_session = FakeSession(first_session.rows)
    job_id = _run_download(store, "nb-1", tmp_path, second_client, second_session)

    job = store.get(job_id)
    assert job is not None and job.status == JobStatus.DONE
    assert second_client.sources.fulltext_calls == []
    assert second_client.artifacts.download_calls == []
    items = store.items(job_id)
    assert {i.status for i in items} == {ItemStatus.SKIPPED}
    assert {i.error for i in items} == {"already downloaded"}


def test_rows_point_at_written_files(store: JobStore, tmp_path: Path) -> None:
    session = FakeSession()
    _run_download(store, "nb-1", tmp_path, FakeClient(_sources(), _artifacts()), session)

    out_dir = tmp_path / "Research Notes_assets"
    assert Path(session.rows["src-1"].local_path) == (out_dir / "sources" / "Paper A.md").absolute()
    assert (
        Path(session.rows["art-1"].local_path) == (out_dir / "artifacts" / "Summary.md").absolute()
    )
    assert session.rows["art-1"].asset_type == "artifact"
    assert session.rows["src-1"].notebook_id == "nb-1"
    assert (out_dir / "chat_history.md").read_text().startswith("**User**: hi")
