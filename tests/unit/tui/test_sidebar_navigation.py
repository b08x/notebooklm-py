from types import SimpleNamespace

from rich.console import Console

from notebooklm.tui.renderers.sidebar import _get_artifact_badges, _parse_domain_tag, render_sidebar
from notebooklm.tui.state import TUIState
from notebooklm.tui.theme import THEME


def test_parse_domain_tag():
    chip, clean, raw = _parse_domain_tag("[GEMINI] Architecture Review")
    assert raw == "GEMINI"
    assert clean == "Architecture Review"
    assert "cyan" in chip
    assert "[GEMINI]" in chip

    chip_claude, clean_claude, raw_claude = _parse_domain_tag("[claude] Prompt engineering")
    assert raw_claude == "CLAUDE"
    assert clean_claude == "Prompt engineering"
    assert "magenta" in chip_claude

    # No tag
    chip_none, clean_none, raw_none = _parse_domain_tag("Plain Title")
    assert chip_none == ""
    assert clean_none == "Plain Title"
    assert raw_none == ""


def test_get_artifact_badges():
    state = TUIState()
    state.notebook_stats["nb-1"] = {
        "has_audio": True,
        "has_notes": True,
        "recent_generated_at": 2000000000.0,  # far future -> recent
    }
    state.notebook_stats["nb-2"] = {
        "has_audio": False,
        "has_notes": True,
        "recent_generated_at": None,
    }

    badges_1 = _get_artifact_badges("nb-1", state)
    assert "🎙️" in badges_1
    assert "📄" in badges_1
    assert "⚡" in badges_1

    badges_2 = _get_artifact_badges("nb-2", state)
    assert "🎙️" not in badges_2
    assert "📄" in badges_2
    assert "⚡" not in badges_2


def test_render_sidebar_displays_chips_and_badges():
    state = TUIState()
    state.notebooks = [
        SimpleNamespace(id="nb-1", title="[CLAUDE] Assistant Design", sources_count=4),
        SimpleNamespace(id="nb-2", title="Standard Notebook", sources_count=1),
    ]
    state.selected_notebook = "nb-1"
    state.notebook_stats["nb-1"] = {"has_audio": True, "has_notes": False}

    panel = render_sidebar(state)
    console = Console(theme=THEME, color_system="truecolor", record=True)
    console.print(panel)
    output = console.export_text()

    assert "Notebooks" in output
    assert "[CLAUDE]" in output
    assert "🎙️" in output
    assert "Commands" in output
    assert "[/] Search" in output
