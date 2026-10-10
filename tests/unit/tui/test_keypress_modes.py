import uuid
from collections.abc import Iterator

import pytest

from notebooklm.tui.jobs.store import JobStatus, JobStore, connect
from notebooklm.tui.keypress import handle_key
from notebooklm.tui.state import Mode, TUIState, View


@pytest.fixture
def store() -> Iterator[JobStore]:
    """Real Redis-backed store under a unique ``nblm:test:`` prefix; fails if Redis is down."""
    client = connect()
    prefix = f"nblm:test:{uuid.uuid4().hex[:10]}:"
    yield JobStore(client, prefix=prefix)
    keys = list(client.scan_iter(match=f"{prefix}*", count=500))
    if keys:
        client.delete(*keys)


@pytest.mark.parametrize("number", ["1", "2", "3", "4", "5", "6"])
def test_number_keys_switch_mode(number: str) -> None:
    state = TUIState()
    assert handle_key(number, state) is True
    assert state.mode == Mode(int(number))


def test_number_keys_pick_views() -> None:
    state = TUIState()
    handle_key("4", state)
    assert state.current_view == View.COMPILER
    handle_key("3", state)
    assert state.current_view == View.ASSESSMENT
    handle_key("6", state)
    assert state.current_view == View.LOGS
    handle_key("1", state)
    assert state.current_view == View.NOTEBOOK_LIST
    assert state.mode == Mode.NOTEBOOKS


def test_ingest_and_jobs_keep_current_view() -> None:
    state = TUIState()
    handle_key("p", state)
    handle_key("2", state)
    assert state.mode == Mode.INGEST
    assert state.current_view == View.COMPILER
    handle_key("5", state)
    assert state.mode == Mode.JOBS
    assert state.current_view == View.COMPILER


def test_letter_keys_still_work_and_set_mode() -> None:
    state = TUIState()
    handle_key("p", state)
    assert state.current_view == View.COMPILER
    assert state.mode == Mode.COMPILER

    handle_key("A", state)
    assert state.current_view == View.ASSESSMENT
    assert state.mode == Mode.FACT_CHECK

    handle_key("L", state)
    assert state.current_view == View.LOGS
    assert state.mode == Mode.LOGS

    handle_key("n", state)
    assert state.current_view == View.NOTEBOOK_LIST
    assert state.mode == Mode.NOTEBOOKS


def test_chat_opens_only_from_notebooks_mode() -> None:
    state = TUIState()
    handle_key("5", state)
    handle_key("c", state)
    assert state.current_view != View.CHAT

    state.mode = Mode.NOTEBOOKS
    handle_key("c", state)
    assert state.current_view == View.CHAT


def test_number_key_in_chat_input_is_appended() -> None:
    state = TUIState()
    handle_key("c", state)
    handle_key("5", state)
    assert state.chat_input == "5"
    assert state.mode == Mode.NOTEBOOKS


def test_number_key_during_search_is_appended() -> None:
    state = TUIState()
    state.searching = True
    handle_key("3", state)
    assert state.search_query == "3"
    assert state.mode == Mode.NOTEBOOKS


def test_jobs_cursor_moves_with_j_and_k(store: JobStore) -> None:
    state = TUIState(job_store=store)
    store.enqueue("download", "nb1")
    store.enqueue("download", "nb2")
    handle_key("5", state)

    handle_key("j", state)
    assert state.jobs_view["cursor"] == 1
    handle_key("k", state)
    assert state.jobs_view["cursor"] == 0


def test_jobs_x_cancels_selected_job(store: JobStore) -> None:
    job_id = store.enqueue("download", "nb1")
    state = TUIState(job_store=store)
    handle_key("5", state)

    handle_key("x", state)

    job = store.get(job_id)
    assert job is not None
    assert job.status == JobStatus.CANCELLED


def test_jobs_R_retries_failed_job(store: JobStore) -> None:
    job_id = store.enqueue("download", "nb1")
    store.finish(job_id, JobStatus.FAILED, error="boom")
    state = TUIState(job_store=store)
    handle_key("5", state)

    handle_key("R", state)

    job = store.get(job_id)
    assert job is not None
    assert job.status == JobStatus.QUEUED


def test_jobs_C_clears_finished(store: JobStore) -> None:
    done_id = store.enqueue("download", "nb1")
    store.finish(done_id, JobStatus.DONE, summary="ok")
    running_id = store.enqueue("download", "nb2")
    state = TUIState(job_store=store)
    handle_key("5", state)

    handle_key("C", state)

    assert store.get(done_id) is None
    assert store.get(running_id) is not None


def test_jobs_f_cycles_status_filter(store: JobStore) -> None:
    store.enqueue("download", "nb1")
    state = TUIState(job_store=store)
    handle_key("5", state)

    seen = []
    for _ in range(4):
        handle_key("f", state)
        seen.append(state.jobs_view.get("status"))
    assert seen == [JobStatus.RUNNING, JobStatus.FAILED, JobStatus.DONE, None]


def test_jobs_keys_without_store_do_not_raise() -> None:
    state = TUIState()
    handle_key("5", state)
    for key in ("x", "R", "C", "j", "k", "f"):
        assert handle_key(key, state) is True
