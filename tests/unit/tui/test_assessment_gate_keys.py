"""TUI y/n/s keys drive the shared ``_app`` HumanGate (fact-40)."""

from __future__ import annotations

import asyncio
import threading

import pytest

from notebooklm.tui.keypress import handle_key
from notebooklm.tui.state import TUIState, View
from notebooklm.tui.views.notebook_detail import _bind_assessment_gate


def _waiting_state() -> tuple[TUIState, asyncio.AbstractEventLoop, threading.Thread, dict]:
    state = TUIState()
    state.current_view = View.ASSESSMENT
    loop = asyncio.new_event_loop()
    ready = threading.Event()
    out: dict = {}

    def owner() -> None:
        asyncio.set_event_loop(loop)

        async def main() -> None:
            gate = _bind_assessment_gate(state)
            ready.set()
            out["check"] = await gate.wait("audio-1", {"text": "x"})

        loop.run_until_complete(main())

    thread = threading.Thread(target=owner)
    thread.start()
    ready.wait(2)
    for _ in range(200):
        if state.assessment_gate.waiting:
            break
        threading.Event().wait(0.005)
    state.assessment_state["hitl_prompt"] = {"chunk": "x", "decision": None}
    return state, loop, thread, out


@pytest.mark.parametrize(("key", "check"), [("y", False), ("n", True)])
def test_y_skips_and_n_fact_checks(key: str, check: bool) -> None:
    state, loop, thread, out = _waiting_state()
    assert handle_key(key, state) is True
    thread.join(2)
    loop.close()
    assert out == {"check": check}


def test_s_toggles_auto_skip_and_releases_gate() -> None:
    state, loop, thread, out = _waiting_state()
    assert handle_key("s", state) is True
    thread.join(2)
    loop.close()
    assert out == {"check": False}
    assert state.assessment_state["auto_skip_meta"] is True
    assert state.assessment_gate.auto_skip is True


def test_gate_starts_in_auto_skip_when_toggle_already_on() -> None:
    state = TUIState()
    state.assessment_state["auto_skip_meta"] = True

    async def main() -> bool:
        return _bind_assessment_gate(state).auto_skip

    assert asyncio.run(main()) is True
