"""``/v1/corpus/factcheck`` routes: gate over HTTP, SSE replay, runs outlive the tab (facts 34-40)."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx

from ._corpus_env import HEADERS, HEDGED, _tag, _wait
from ._live import live_server


def _live_events(base: str, path: str, until: str) -> list[dict[str, Any]]:
    """Read SSE events from a real server until ``until`` arrives (then disconnect)."""
    events = []
    with (
        httpx.Client(base_url=base, headers=HEADERS, timeout=10) as http,
        http.stream("GET", path) as resp,
    ):
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        for line in resp.iter_lines():
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))
                if events[-1]["type"] == until:
                    break
    return events


def _start(env: Any, **body: Any) -> Any:
    return env.http.post("/v1/corpus/factcheck/runs", json=body)


def test_sfl_required_is_actionable(env: Any) -> None:
    resp = _start(env, scope={"document_ids": [env.doc_a]})
    assert resp.status_code == 409
    err = resp.json()["error"]
    assert err["category"] == "sfl_required" and "run sfl_tag first" in err["message"]
    assert err["scope"]["document_ids"] == [env.doc_a]
    assert _start(env, scope={"document_ids": ["nope"]}).status_code == 404
    assert _start(env, scope={}).status_code == 422


def test_interactive_gate_over_http_and_sse_replay(env: Any) -> None:
    asyncio.run(_tag(env.prefix, {"It might rain": HEDGED}))
    env.http.close()  # the TestClient's lifespan ends; the live server runs its own
    with live_server(env.app) as base, httpx.Client(base_url=base, headers=HEADERS) as http:
        resp = http.post(
            "/v1/corpus/factcheck/runs",
            json={"scope": {"document_ids": [env.doc_b]}, "gate_source": "rule"},
        )
        assert resp.status_code == 201
        run = resp.json()
        run_id = run["id"]
        assert run["total"] == 2

        # Stream until the hedged chunk reaches the gate, then "close the tab".
        first = _live_events(base, f"/v1/corpus/factcheck/runs/{run_id}/events", until="gate")
        gate = first[-1]
        assert gate["item_id"] == "0002" and gate["gate"]["reason"] == "hedge cue: might"
        assert [e["seq"] for e in first] == list(range(1, len(first) + 1))

        # The run keeps waiting with no subscriber; reopening shows its state.
        snap = http.get(f"/v1/corpus/factcheck/runs/{run_id}").json()
        assert snap["status"] == "running" and snap["waiting"][0]["item_id"] == "0002"
        item0 = snap["items"][0]
        assert item0["status"] == "verified"
        assert item0["context"]["after"][0]["text"] == "It might rain"
        assert item0["sfl"]["interpersonal"]["tenor"] == ["formality: informal"]
        assert item0["sift"] == {"stop": "done"} and item0["rationale"] == "agree"

        # Wrong item → 409; pressing N fact-checks it anyway.
        bad = http.post(
            f"/v1/corpus/factcheck/runs/{run_id}/decision",
            json={"item_id": "0001", "decision": "skip"},
        )
        assert bad.status_code == 409
        ok = http.post(
            f"/v1/corpus/factcheck/runs/{run_id}/decision",
            json={"item_id": "0002", "decision": "fact_check"},
        )
        assert ok.json()["ok"] is True

        # Reconnect with ?after: replay starts right after the last seen event.
        rest = _live_events(
            base, f"/v1/corpus/factcheck/runs/{run_id}/events?after={gate['seq']}", "run_finished"
        )
        assert rest[0]["seq"] == gate["seq"] + 1 and rest[0]["type"] == "gate_resolved"
        assert rest[-1]["status"] == "finished"
        final = http.get(f"/v1/corpus/factcheck/runs/{run_id}").json()
        assert final["counts"]["verified"] == 2
        detail = http.get(f"/v1/corpus/chunks/{env.ids['It might rain']}").json()
        assert detail["latest_fact_check"]["verdict"] == "supported"
        listed = http.get("/v1/corpus/factcheck/runs").json()["items"]
        assert [r["id"] for r in listed] == [run_id] and "items" not in listed[0]


def test_auto_skip_pause_cancel(env: Any) -> None:
    asyncio.run(_tag(env.prefix, {"It might rain": HEDGED}))
    run_id = _start(env, scope={"document_ids": [env.doc_b]}).json()["id"]
    _wait(lambda: env.http.get(f"/v1/corpus/factcheck/runs/{run_id}").json()["waiting"])
    on = env.http.post(f"/v1/corpus/factcheck/runs/{run_id}/auto-skip", json={"on": True})
    assert on.json()["auto_skip"] is True
    _wait(
        lambda: env.http.get(f"/v1/corpus/factcheck/runs/{run_id}").json()["status"] == "finished"
    )
    snap = env.http.get(f"/v1/corpus/factcheck/runs/{run_id}").json()
    assert [i["status"] for i in snap["items"]] == ["verified", "skipped"]

    ids = [env.ids["It might rain"]]
    run2 = _start(env, scope={"external_ids": ids}).json()["id"]
    _wait(lambda: env.http.get(f"/v1/corpus/factcheck/runs/{run2}").json()["waiting"])
    assert env.http.post(f"/v1/corpus/factcheck/runs/{run2}/pause").json()["status"] == "paused"
    assert env.http.post(f"/v1/corpus/factcheck/runs/{run2}/resume").json()["status"] == "running"
    env.http.post(f"/v1/corpus/factcheck/runs/{run2}/cancel")
    _wait(lambda: env.http.get(f"/v1/corpus/factcheck/runs/{run2}").json()["status"] == "cancelled")
    assert env.http.get("/v1/corpus/factcheck/runs/nope").status_code == 404
    assert env.http.get("/v1/corpus/factcheck/runs/nope/events").status_code == 404


def test_auto_mode_with_preset_auto_skip(env: Any) -> None:
    asyncio.run(_tag(env.prefix, {"It might rain": HEDGED}))
    run_id = _start(
        env, scope={"run_ids": [env.run_b]}, gate_mode="interactive", auto_skip=True
    ).json()["id"]
    _wait(
        lambda: env.http.get(f"/v1/corpus/factcheck/runs/{run_id}").json()["status"] == "finished"
    )
    health = env.http.get("/v1/corpus/health").json()
    assert health["factcheck_runs"] == []
