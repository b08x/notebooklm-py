import pytest
from unittest.mock import MagicMock
from notebooklm.tui.state import TUIState, View
from notebooklm.tui.views.assessment_view import AssessmentView
from rich.layout import Layout

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
