import json
from unittest.mock import MagicMock, patch

import pytest

from notebooklm._preprocessing.transcription import (
    AssemblyAIAdapter,
    DeepgramAdapter,
    SpeechmaticsAdapter,
    TranscribeCppAdapter,
    TranscriptionService,
)


@pytest.fixture
def dummy_audio(tmp_path):
    p = tmp_path / "test.mp3"
    p.write_bytes(b"dummy audio data")
    return str(p)


@patch("httpx.Client")
def test_deepgram_adapter(mock_client_class, dummy_audio):
    mock_client = MagicMock()
    mock_client_class.return_value.__enter__.return_value = mock_client

    mock_response = MagicMock()
    mock_response.json.return_value = {
        "results": {"channels": [{"alternatives": [{"transcript": "deepgram transcription text"}]}]}
    }
    mock_client.post.return_value = mock_response

    adapter = DeepgramAdapter(api_key="test_key")
    service = TranscriptionService(adapter)
    result = service.transcribe_audio(dummy_audio)

    assert result["text"] == "deepgram transcription text"
    assert result["provider"] == "deepgram"
    assert "diarization" in result


@patch("httpx.Client")
def test_assemblyai_adapter(mock_client_class, dummy_audio):
    mock_client = MagicMock()
    mock_client_class.return_value.__enter__.return_value = mock_client

    mock_upload_resp = MagicMock()
    mock_upload_resp.json.return_value = {"upload_url": "https://api.assemblyai.com/v2/upload/123"}

    mock_submit_resp = MagicMock()
    mock_submit_resp.json.return_value = {"id": "transcript_123"}

    mock_client.post.side_effect = [mock_upload_resp, mock_submit_resp]

    mock_poll_resp = MagicMock()
    mock_poll_resp.json.return_value = {
        "status": "completed",
        "text": "assemblyai transcription text",
        "utterances": [],
    }
    mock_client.get.return_value = mock_poll_resp

    adapter = AssemblyAIAdapter(api_key="test_key")
    service = TranscriptionService(adapter)
    result = service.transcribe_audio(dummy_audio)

    assert result["text"] == "assemblyai transcription text"
    assert result["provider"] == "assemblyai"
    assert "diarization" in result


@patch("httpx.Client")
def test_speechmatics_adapter(mock_client_class, dummy_audio):
    mock_client = MagicMock()
    mock_client_class.return_value.__enter__.return_value = mock_client

    mock_submit_resp = MagicMock()
    mock_submit_resp.json.return_value = {"id": "job_123"}
    mock_client.post.return_value = mock_submit_resp

    mock_poll_resp = MagicMock()
    mock_poll_resp.json.return_value = {"job": {"status": "done"}}

    mock_transcript_resp = MagicMock()
    mock_transcript_resp.json.return_value = {
        "results": [
            {"type": "word", "alternatives": [{"content": "speechmatics"}]},
            {"type": "word", "alternatives": [{"content": "transcription"}]},
        ]
    }

    mock_client.get.side_effect = [mock_poll_resp, mock_transcript_resp]

    adapter = SpeechmaticsAdapter(api_key="test_key")
    service = TranscriptionService(adapter)
    result = service.transcribe_audio(dummy_audio)

    assert result["text"] == "speechmatics transcription"
    assert result["provider"] == "speechmatics"
    assert "diarization" in result


@patch("subprocess.run")
def test_transcribecpp_adapter(mock_run, tmp_path):
    mock_run.return_value = MagicMock(stdout="fallback text", returncode=0)

    audio_path = tmp_path / "test.mp3"
    audio_path.touch()

    json_path = tmp_path / "test.mp3.json"
    json_path.write_text(json.dumps({"text": "transcribecpp transcription text"}))

    adapter = TranscribeCppAdapter(model_path="ggml-model.bin")
    service = TranscriptionService(adapter)
    result = service.transcribe_audio(str(audio_path))

    assert result["text"] == "transcribecpp transcription text"
    assert result["provider"] == "transcribe_cpp"
    assert "diarization" in result

    mock_run.assert_called_once()
    assert mock_run.call_args[0][0] == [
        "main",
        "-m",
        "ggml-model.bin",
        "-f",
        str(audio_path),
        "-oj",
    ]

    assert not json_path.exists()
