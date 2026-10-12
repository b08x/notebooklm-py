"""Per-clause progress from ``tag_children`` via ``GroupProgress.child`` (QA fact 10)."""

from __future__ import annotations

import asyncio
from typing import Any

from notebooklm._app.sfl_tagging import ChildRow, GroupProgress, tag_children

EVENTS: list[tuple[int, int, int]] = []


class Engine:
    def forward(self, text: str) -> dict[str, Any]:
        return {"ideational": {}, "interpersonal": {"mood": "declarative", "modality": "high"}}


async def fake_save(session_factory: Any, values: dict[int, dict[str, Any]]) -> None:
    return None


def _progress(events: list[tuple[int, int, int]]) -> GroupProgress:
    def start(number: int, total: int, parent_index: int, n_children: int) -> int:
        return n_children

    def done(handle: int, n_children: int, n_failed: int, first_error: str | None) -> None:
        return None

    def child(clauses_done: int, total: int, parent_number: int) -> None:
        events.append((clauses_done, total, parent_number))

    return GroupProgress(start=start, done=done, child=child)


def _row(id: int, parent_id: int, parent_index: int, text: str) -> ChildRow:
    return ChildRow(id=id, parent_id=parent_id, parent_index=parent_index, text=text)


def _run(children: list[ChildRow], events: list[tuple[int, int, int]]) -> tuple[int, int]:
    return asyncio.run(
        tag_children(
            children,
            session_factory=None,  # type: ignore[arg-type] - save is faked
            progress=_progress(events),
            engine=Engine(),
            lm=object(),
            save=fake_save,
        )
    )


def test_single_child_emits_before_and_after_progress() -> None:
    events: list[tuple[int, int, int]] = []
    assert _run([_row(1, 10, 0, "Water boils.")], events) == (1, 0)
    assert events == [(0, 1, 1), (1, 1, 1)]


def test_three_children_in_two_parents_progress_monotonically() -> None:
    events: list[tuple[int, int, int]] = []
    children = [
        _row(1, 10, 0, "The cat sat."),
        _row(2, 10, 0, "It was warm."),
        _row(3, 11, 1, "Dogs bark."),
    ]
    assert _run(children, events) == (3, 0)
    assert [e[0] for e in events] == [0, 1, 1, 2, 2, 3]  # monotonic done 0…3
    assert [e[1] for e in events] == [3] * 6
    assert [e[2] for e in events] == [1, 1, 1, 1, 2, 2]  # parent number per child


def test_failed_child_still_reports_progress() -> None:
    class FailingEngine(Engine):
        def forward(self, text: str) -> dict[str, Any]:
            if text == "boom":
                raise ValueError("boom")
            return super().forward(text)

    events: list[tuple[int, int, int]] = []

    def run() -> tuple[int, int]:
        return asyncio.run(
            tag_children(
                [_row(1, 10, 0, "boom")],
                session_factory=None,  # type: ignore[arg-type]
                progress=_progress(events),
                engine=FailingEngine(),
                lm=object(),
                save=fake_save,
            )
        )

    assert run() == (0, 1)
    assert [e[0] for e in events] == [0, 1]
