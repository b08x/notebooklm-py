import ast
import pathlib

from notebooklm._app.assessment import AssessmentChunk
from notebooklm.tui.state import TUIState
from notebooklm.tui.views.assessment_view import ENTITY_STYLES, AssessmentView


def test_assessment_view_render():
    state = TUIState()
    state.assessment_state = {
        "audio_metadata": "Duration: 5m",
        "system_instructions": "Be accurate",
        "chunks": ["Chunk 1"],
        "llm_score": "8/10",
    }
    view = AssessmentView(state)
    left, right = view.render()
    assert left.title == "Assessment Controls"
    assert "Contextualized Source Chunks" in right.title


def test_assessment_view_renders_entity_styling_for_known_entities():
    chunk = AssessmentChunk(
        text="Acme Corp hired Jane.",
        clause_external_id="artifact-1:0",
        topic_id=0,
        entities=[("Acme Corp", "ORG"), ("Jane", "PERSON")],
    )
    state = TUIState()
    state.assessment_state = {"chunks": [chunk]}

    view = AssessmentView(state)
    _, right = view.render()

    line = right.renderable.renderables[0]
    spans = {(s.style) for s in line.spans}
    assert ENTITY_STYLES["ORG"] in spans
    assert ENTITY_STYLES["PERSON"] in spans


def test_assessment_view_gutter_is_neutral_before_fact_check():
    chunk = AssessmentChunk(text="Unchecked chunk.", clause_external_id="artifact-1:0")
    state = TUIState()
    state.assessment_state = {"chunks": [chunk]}

    view = AssessmentView(state)
    _, right = view.render()

    line = right.renderable.renderables[0]
    assert line.plain.startswith("?")


def test_assessment_view_gutter_reflects_fact_check_result():
    chunk = AssessmentChunk(
        text="Checked chunk.", clause_external_id="artifact-1:0", fact_check_passed=True
    )
    state = TUIState()
    state.assessment_state = {"chunks": [chunk], "fact_check_framework_available": True}

    view = AssessmentView(state)
    _, right = view.render()

    line = right.renderable.renderables[0]
    assert line.plain.startswith("✓")

    chunk.fact_check_passed = False
    view = AssessmentView(state)
    _, right = view.render()
    line = right.renderable.renderables[0]
    assert line.plain.startswith("✗")


def test_assessment_view_module_has_no_pipeline_or_generate_assessment_imports():
    """Guardrail (mirrors tests/_guardrails): orchestration must stay in _app."""
    path = (
        pathlib.Path(__file__).resolve().parents[3]
        / "src"
        / "notebooklm"
        / "tui"
        / "views"
        / "assessment_view.py"
    )
    tree = ast.parse(path.read_text(encoding="utf-8"))

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            assert "PreprocessingPipeline" not in mod
            names = [alias.name for alias in node.names]
            assert "PreprocessingPipeline" not in names
            assert "generate_assessment" not in names
