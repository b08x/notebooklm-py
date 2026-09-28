import datetime
from types import SimpleNamespace

from rich.console import Console

from notebooklm.tui.renderers.main import format_relative_time, render_main
from notebooklm.tui.state import TUIState, View
from notebooklm.tui.theme import THEME


def test_format_relative_time():
    fixed_now = datetime.datetime(2026, 9, 28, 14, 0, 0, tzinfo=datetime.timezone.utc)

    # None and empty
    assert format_relative_time(None) == ""
    assert format_relative_time("invalid") == ""

    # Just now (<60s)
    ts_just_now = fixed_now - datetime.timedelta(seconds=20)
    assert format_relative_time(ts_just_now, now=fixed_now) == "just now"
    assert format_relative_time(ts_just_now.timestamp(), now=fixed_now.timestamp()) == "just now"

    # Minutes (<3600s)
    ts_2m = fixed_now - datetime.timedelta(minutes=2)
    assert format_relative_time(ts_2m, now=fixed_now) == "2m ago"

    # Hours (<86400s)
    ts_3h = fixed_now - datetime.timedelta(hours=3)
    assert format_relative_time(ts_3h, now=fixed_now) == "3h ago"

    # Yesterday (<172800s)
    ts_yesterday = fixed_now - datetime.timedelta(hours=28)
    assert format_relative_time(ts_yesterday, now=fixed_now) == "Yesterday"

    # Specific past date same year
    ts_earlier = datetime.datetime(2026, 9, 15, 10, 0, 0, tzinfo=datetime.timezone.utc)
    assert format_relative_time(ts_earlier, now=fixed_now) == "Sep 15"

    # Past date previous year
    ts_prev_year = datetime.datetime(2025, 9, 15, 10, 0, 0, tzinfo=datetime.timezone.utc)
    assert format_relative_time(ts_prev_year, now=fixed_now) == "Sep 15, 2025"


def test_render_main_notebook_list_with_artifact_stats():
    fixed_now = datetime.datetime(2026, 9, 28, 14, 0, 0, tzinfo=datetime.timezone.utc)
    audio_ts = (fixed_now - datetime.timedelta(hours=2)).timestamp()

    state = TUIState()
    state.current_view = View.NOTEBOOK_LIST
    state.notebooks = [
        SimpleNamespace(id="nb-1", title="AI Research Hub", sources_count=5),
    ]
    state.selected_notebook = "nb-1"
    state.notebook_stats["nb-1"] = {
        "total_artifacts": 3,
        "artifact_count": 3,
        "counts": {"audio": 1, "note": 2},
        "has_audio": True,
        "has_notes": True,
        "recent_generated_at": audio_ts,
        "artifacts": [
            {"id": "a-1", "kind": "audio", "title": "Audio Deep Dive", "timestamp": audio_ts},
            {"id": "a-2", "kind": "note", "title": "Study Guide", "timestamp": audio_ts - 3600},
        ],
    }

    results_panel, detail_panel = render_main(state)
    console = Console(theme=THEME, color_system="truecolor", record=True)
    console.print(results_panel)
    output = console.export_text()

    assert "AI Research Hub" in output
    assert "5 Sources" in output
    assert "Artifacts" in output
    assert "3" in output
    assert "Audio (1)" in output
    assert "Note (2)" in output
    assert "Audio Overview" in output
    assert "Ready" in output
    assert "Last Generated" in output


def test_render_main_notebook_list_without_stats():
    state = TUIState()
    state.current_view = View.NOTEBOOK_LIST
    state.notebooks = [
        SimpleNamespace(id="nb-empty", title="Empty Notebook", sources_count=0),
    ]
    state.selected_notebook = "nb-empty"

    results_panel, detail_panel = render_main(state)
    console = Console(theme=THEME, color_system="truecolor", record=True)
    console.print(results_panel)
    output = console.export_text()

    assert "Empty Notebook" in output
    assert "0 Sources" in output
    assert "[Enter] to view details." in output


def test_render_main_notebook_detail_with_artifact_stats():
    fixed_now = datetime.datetime(2026, 9, 28, 14, 0, 0, tzinfo=datetime.timezone.utc)
    audio_ts = (fixed_now - datetime.timedelta(hours=2)).timestamp()

    state = TUIState()
    state.current_view = View.NOTEBOOK_DETAIL
    state.notebooks = [
        SimpleNamespace(id="nb-1", title="AI Research Hub", sources_count=5),
    ]
    state.selected_notebook = "nb-1"
    state.notebook_stats["nb-1"] = {
        "source_count": 5,
        "total_artifacts": 2,
        "counts": {"audio": 1, "note": 1},
        "has_audio": True,
        "recent_generated_at": audio_ts,
        "artifacts": [
            {"id": "a-1", "kind": "audio", "title": "Audio Deep Dive", "timestamp": audio_ts},
        ],
    }

    actions_panel, detail_panel = render_main(state)
    console = Console(theme=THEME, color_system="truecolor", record=True)
    console.print(detail_panel)
    output = console.export_text()

    assert "Notebook Statistics" in output
    assert "Sources" in output
    assert "Artifacts" in output
    assert "Audio Overview" in output
    assert "Ready" in output
    assert "Last Generated" in output
