import os

from notebooklm._app.assessment import AssessmentChunk
from notebooklm.tui.keypress import handle_key
from notebooklm.tui.state import TUIState, View
from notebooklm.tui.views.assessment_view import AssessmentView


def test_assessment_view_renders_export_key_hint():
    state = TUIState()
    state.assessment_state = {
        "audio_metadata": "Duration: 5m",
        "system_instructions": "Be accurate",
        "chunks": ["Chunk 1"],
        "llm_score": "8/10",
    }
    view = AssessmentView(state)
    left, _ = view.render()
    render_text = str(left)
    assert "export .ass" in render_text or "e" in render_text


def test_assessment_keypress_e_exports_ass(tmp_path):
    state = TUIState()
    state.current_view = View.ASSESSMENT
    state.download_dir = str(tmp_path)

    chunk = AssessmentChunk(
        text="Testing ASS export keypress.",
        clause_external_id="art-test:0",
        fact_check_passed=True,
        fact_check_citations="Verified.",
        speaker="Speaker 1",
    )
    state.assessment_state = {
        "artifact_id": "art-test",
        "system_instructions": "Check accuracy",
        "audio_metadata": "{}",
        "transcript": "Testing ASS export keypress.",
        "chunks": [chunk],
    }

    result = handle_key("e", state)
    assert result is True

    expected_ass_path = str(tmp_path / "artifacts" / "assessment_art-test.ass")
    assert os.path.exists(expected_ass_path)
    assert "Exported ASS subtitles to" in (state.error_message or "")

    with open(expected_ass_path, encoding="utf-8") as f:
        content = f.read()

    assert "[Script Info]" in content
    assert "Testing ASS export keypress." in content
    assert "FactCheck_Pass" in content
