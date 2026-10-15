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


def test_sfl_bypassed_if_empty_list_diarization():
    # Regression test: list diarization without utterances must not crash with AttributeError
    result = analyze_transcript("fake transcript", diarization=[])
    assert "error" in result
    assert "Missing or failed diarization" in result["error"]


def test_sfl_with_assemblyai_list_diarization():
    # AssemblyAI returns a list of utterance dicts
    assemblyai_diarization = [
        {"speaker": "A", "text": "Good morning and welcome to the show."},
        {"speaker": "B", "text": "Thanks for having me, excited to be here."},
    ]
    mock_engine = MagicMock()
    with patch.object(sfl_engine_module, "SFLEngine", return_value=mock_engine):
        mock_engine.return_value = {
            "ideational": {"participants": []},
            "interpersonal": {"tenor": "conversational"},
        }

        result = analyze_transcript("fake transcript", diarization=assemblyai_diarization)
        assert "profiles" in result
        assert "Speaker A" in result["profiles"]
        assert "Speaker B" in result["profiles"]
        assert result["profiles"]["Speaker A"]["utterances"] == 1
        assert result["profiles"]["Speaker B"]["utterances"] == 1


def test_sfl_with_deepgram_dict_diarization():
    deepgram_diarization = {
        "results": {
            "channels": [
                {
                    "alternatives": [
                        {
                            "paragraphs": {
                                "paragraphs": [
                                    {
                                        "speaker": 0,
                                        "sentences": [
                                            {"text": "First sentence by speaker zero."},
                                            {"text": "Second sentence by speaker zero."},
                                        ],
                                    },
                                    {
                                        "speaker": 1,
                                        "sentences": [
                                            {"text": "Response by speaker one."},
                                        ],
                                    },
                                ]
                            }
                        }
                    ]
                }
            ]
        }
    }
    mock_engine = MagicMock()
    with patch.object(sfl_engine_module, "SFLEngine", return_value=mock_engine):
        mock_engine.return_value = {
            "ideational": {"participants": []},
            "interpersonal": {"tenor": "formal"},
        }

        result = analyze_transcript("fake transcript", diarization=deepgram_diarization)
        assert "profiles" in result
        assert "Speaker 0" in result["profiles"]
        assert "Speaker 1" in result["profiles"]
        assert result["profiles"]["Speaker 0"]["utterances"] == 1
        assert result["profiles"]["Speaker 1"]["utterances"] == 1


class _BatchEngine:
    """Stand-in for AgentSFLEngine: records batch calls."""

    batch = True

    def __init__(self, tenors):
        self.tenors = tenors
        self.batches = []

    def forward_batch(self, texts):
        self.batches.append(list(texts))
        return [{"ideational": {}, "interpersonal": {"tenor": t}} for t in self.tenors]

    def __call__(self, utterance):
        raise AssertionError("per-segment call made despite forward_batch")


def test_analyze_transcript_batches_segments_with_agent_engine():
    diarization = {
        "segments": [
            {"speaker": "Speaker 0", "text": "We present the findings."},
            {"speaker": "Speaker 1", "text": "lol yeah whatever"},
            {"speaker": "Speaker 0", "text": "As shown above."},
        ]
    }
    engine = _BatchEngine(["formal", "slang", "formal"])
    result = analyze_transcript("t", diarization, engine=engine)
    assert engine.batches == [["We present the findings.", "lol yeah whatever", "As shown above."]]
    assert result["profiles"]["Speaker 0"]["dominant_tenor"] == "formal"
    assert len(result["anomalies"]) == 1  # formal -> slang shift


def test_analyze_transcript_tolerates_failed_and_nested_results():
    diarization = {
        "segments": [
            {"speaker": "A", "text": "one"},
            {"speaker": "A", "text": "two"},
        ]
    }

    class Mixed(_BatchEngine):
        def forward_batch(self, texts):
            return [RuntimeError("agent timed out"), {"interpersonal": {"tenor": {"x": 1}}}]

    result = analyze_transcript("t", diarization, engine=Mixed([]))
    assert result["profiles"]["A"]["tenors"] == ["neutral", "neutral"]
