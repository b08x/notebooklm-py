from rich.layout import Layout

from notebooklm.tui.state import TUIState
from notebooklm.tui.views.assessment_view import AssessmentView


def test_assessment_view_render():
    state = TUIState()
    state.assessment_state = {
        "audio_metadata": "Duration: 5m",
        "system_instructions": "Be accurate",
        "chunks": ["Chunk 1"],
        "llm_score": "8/10"
    }
    view = AssessmentView(state)
    layout = view.__rich__()
    assert isinstance(layout, Layout)
