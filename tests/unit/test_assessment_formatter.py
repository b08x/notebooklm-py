from notebooklm._app.assessment import AssessmentChunk, AssessmentResult
from notebooklm._app.assessment_formatter import generate_markdown_report


def test_markdown_report_data_quality():
    chunk = AssessmentChunk(text="The sky is green", clause_external_id="123:0")
    chunk.fact_check_passed = False

    res = AssessmentResult(
        system_instructions="",
        audio_metadata="",
        transcript="",
        chunks=[chunk],
        sfl_metrics={
            "anomalies": [{"speaker": "Host 1", "issue": "Semantic anomaly: sudden shift", "segment_index": 0}]
        }
    )

    report = generate_markdown_report(res)
    assert "Data Quality" in report
    assert "[!WARNING]" in report
    assert "flagged semantic anomalies or failed fact checks" in report
    assert "Semantic anomaly: sudden shift" in report
    assert "Failed Fact Check" in report

def test_markdown_report_pass():
    chunk = AssessmentChunk(text="The sky is blue", clause_external_id="123:0")
    chunk.fact_check_passed = True

    res = AssessmentResult(
        system_instructions="",
        audio_metadata="",
        transcript="",
        chunks=[chunk],
        sfl_metrics={}
    )

    report = generate_markdown_report(res)
    assert "Data Quality" in report
    assert "[!NOTE]" in report
    assert "passed basic checks" in report
