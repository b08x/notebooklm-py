from unittest.mock import MagicMock, patch

from notebooklm._preprocessing import sfl_engine as sfl_engine_module
from notebooklm._preprocessing.sfl_engine import analyze_transcript


def test_sfl_semantic_anomaly():
    diarization = {
        "speakers": 2,
        "segments": [
            {
                "speaker": "Host 1",
                "text": "We shall commence our analysis on the underlying macroeconomic factors.",
            },
            {"speaker": "Host 2", "text": "Yo that's lit fam, let's get it."},
        ],
    }

    mock_engine = MagicMock()
    with patch.object(sfl_engine_module, "SFLEngine", return_value=mock_engine):
        # Mock responses from LLM
        def side_effect(utterance, **kwargs):
            if "commence" in utterance:
                return {"ideational": {"participants": []}, "interpersonal": {"tenor": "academic"}}
            else:
                return {"ideational": {"participants": []}, "interpersonal": {"tenor": "slang"}}

        mock_engine.side_effect = side_effect

        result = analyze_transcript("fake transcript", diarization)

        assert "anomalies" in result
        assert len(result["anomalies"]) > 0
        anomaly = result["anomalies"][0]
        assert "Semantic anomaly: Sudden shift in tenor from academic to slang" in anomaly["issue"]
        assert result["profiles"]["Host 1"]["dominant_tenor"] == "academic"
        assert result["profiles"]["Host 2"]["dominant_tenor"] == "slang"


def test_sfl_bypassed_if_missing_diarization():
    result = analyze_transcript("fake transcript", diarization={})
    assert "error" in result
    assert "Missing or failed diarization" in result["error"]
