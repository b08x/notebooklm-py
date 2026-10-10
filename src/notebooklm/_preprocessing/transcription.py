from __future__ import annotations

import json
import os
import subprocess
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx


class TranscriptionAdapter(ABC):
    """Abstract base class for audio transcription adapters."""

    @abstractmethod
    def transcribe(self, audio_path: str) -> dict[str, Any]:
        """
        Transcribe the audio file at the given path.

        Returns a dictionary containing at least:
        - 'text': the full transcribed text
        - 'diarization': optional diarization data if supported/requested
        """
        pass


_CONTENT_TYPES = {
    ".flac": "audio/flac",
    ".wav": "audio/wav",
    ".m4a": "audio/mp4",
    ".mp4": "video/mp4",
    ".ogg": "audio/ogg",
    ".webm": "audio/webm",
}


def content_type_for(audio_path: str) -> str:
    """MIME type for an audio file by extension (``audio/mpeg`` by default)."""
    return _CONTENT_TYPES.get(Path(audio_path).suffix.lower(), "audio/mpeg")


class DeepgramAdapter(TranscriptionAdapter):
    def __init__(
        self, api_key: str | None = None, diarize: bool = True, language: str | None = "en"
    ):
        resolved_key = api_key or os.environ.get("DEEPGRAM_API_KEY")
        if not resolved_key:
            raise ValueError("Deepgram API key is required")
        self.api_key: str = resolved_key
        self.diarize = diarize
        #: ``None`` = auto-detect.
        self.language = language

    def transcribe(self, audio_path: str) -> dict[str, Any]:
        language = f"language={self.language}" if self.language else "detect_language=true"
        diarize = "&diarize=true&diarize_model=latest" if self.diarize else ""
        url = (
            "https://api.deepgram.com/v1/listen"
            f"?model=nova-3&{language}&smart_format=true"
            f"{diarize}&punctuate=true&paragraphs=true"
            "&filler_words=true&numerals=true"
        )
        headers = {
            "Authorization": f"Token {self.api_key}",
            "Content-Type": content_type_for(audio_path),
        }
        with open(audio_path, "rb") as f:
            audio_data = f.read()

        with httpx.Client(timeout=300.0) as client:
            response = client.post(url, content=audio_data, headers=headers)
            if response.status_code >= 400:
                raise Exception(f"Deepgram API error {response.status_code}: {response.text}")
            response.raise_for_status()
            data = response.json()

            channels = data.get("results", {}).get("channels", [])
            text = (
                channels[0].get("alternatives", [{}])[0].get("transcript", "") if channels else ""
            )

            return {
                "text": text,
                "diarization": data,
                "provider": "deepgram",
            }


class AssemblyAIAdapter(TranscriptionAdapter):
    def __init__(
        self, api_key: str | None = None, diarize: bool = True, language: str | None = None
    ):
        resolved_key = api_key or os.environ.get("ASSEMBLYAI_API_KEY")
        if not resolved_key:
            raise ValueError("AssemblyAI API key is required")
        self.api_key: str = resolved_key
        self.diarize = diarize
        self.language = language

    def transcribe(self, audio_path: str) -> dict[str, Any]:
        headers = {"authorization": self.api_key}
        with httpx.Client(timeout=300.0) as client:
            with open(audio_path, "rb") as f:
                upload_resp = client.post(
                    "https://api.assemblyai.com/v2/upload", content=f, headers=headers
                )
                upload_resp.raise_for_status()
                audio_url = upload_resp.json()["upload_url"]

            transcript_req: dict[str, Any] = {
                "audio_url": audio_url,
                "speaker_labels": self.diarize,
                "speech_model": "best",
                "format_text": True,
                "punctuate": True,
            }
            if self.language:
                transcript_req["language_code"] = self.language
            else:
                transcript_req["language_detection"] = True
            submit_resp = client.post(
                "https://api.assemblyai.com/v2/transcript", json=transcript_req, headers=headers
            )
            submit_resp.raise_for_status()
            transcript_id = submit_resp.json()["id"]

            while True:
                poll_resp = client.get(
                    f"https://api.assemblyai.com/v2/transcript/{transcript_id}", headers=headers
                )
                poll_resp.raise_for_status()
                poll_data = poll_resp.json()
                status = poll_data["status"]

                if status == "completed":
                    return {
                        "text": poll_data["text"],
                        "diarization": poll_data.get("utterances", []),
                        "provider": "assemblyai",
                    }
                elif status == "error":
                    raise Exception(f"AssemblyAI transcription failed: {poll_data['error']}")
                time.sleep(3)


class SpeechmaticsAdapter(TranscriptionAdapter):
    def __init__(
        self, api_key: str | None = None, diarize: bool = True, language: str | None = "en"
    ):
        resolved_key = api_key or os.environ.get("SPEECHMATICS_API_KEY")
        if not resolved_key:
            raise ValueError("Speechmatics API key is required")
        self.api_key: str = resolved_key
        self.diarize = diarize
        self.language = language

    def transcribe(self, audio_path: str) -> dict[str, Any]:
        url = "https://asr.api.speechmatics.com/v2/jobs"
        headers = {"Authorization": f"Bearer {self.api_key}"}

        with httpx.Client(timeout=300.0) as client:
            config = {
                "type": "transcription",
                "transcription_config": {
                    "operating_point": "enhanced",
                    "language": self.language or "auto",
                    "diarization": "speaker" if self.diarize else "none",
                },
            }
            with open(audio_path, "rb") as f:
                files: dict[str, tuple[str | None, Any, str]] = {
                    "data_file": (Path(audio_path).name, f, content_type_for(audio_path)),
                    "config": (None, json.dumps(config), "application/json"),
                }
                submit_resp = client.post(url, files=files, headers=headers)
                submit_resp.raise_for_status()
                job_id = submit_resp.json()["id"]

            while True:
                poll_resp = client.get(f"{url}/{job_id}", headers=headers)
                poll_resp.raise_for_status()
                job_data = poll_resp.json()
                status = job_data["job"]["status"]

                if status == "done":
                    break
                elif status == "rejected":
                    raise Exception(f"Speechmatics job rejected: {job_data.get('errors')}")
                time.sleep(3)

            transcript_resp = client.get(
                f"{url}/{job_id}/transcript?format=json-v2", headers=headers
            )
            transcript_resp.raise_for_status()
            transcript_data = transcript_resp.json()

            results = transcript_data.get("results", [])
            text = " ".join(
                r["alternatives"][0]["content"]
                for r in results
                if r["type"] == "word" and r["alternatives"]
            )

            return {
                "text": text,
                "diarization": transcript_data,
                "provider": "speechmatics",
            }


#: Env vars for the local transcribe.cpp (whisper.cpp-style) adapter.
TRANSCRIBE_CPP_MODEL_ENV = "NOTEBOOKLM_TRANSCRIBE_CPP_MODEL"
TRANSCRIBE_CPP_BIN_ENV = "NOTEBOOKLM_TRANSCRIBE_CPP_BIN"


class TranscribeCppAdapter(TranscriptionAdapter):
    def __init__(
        self,
        model_path: str | None = None,
        executable_path: str | None = None,
        diarize: bool = False,
        language: str | None = None,
    ):
        #: Validated when transcribing, so an unconfigured fallback adapter can be built.
        self.model_path: str | None = model_path or os.environ.get(TRANSCRIBE_CPP_MODEL_ENV)
        self.executable_path = executable_path or os.environ.get(TRANSCRIBE_CPP_BIN_ENV, "main")
        self.diarize = diarize
        self.language = language

    def transcribe(self, audio_path: str) -> dict[str, Any]:
        if not self.model_path:
            raise ValueError(
                f"model_path is required for transcribe.cpp (set {TRANSCRIBE_CPP_MODEL_ENV})"
            )
        cmd = [self.executable_path, "-m", self.model_path, "-f", audio_path, "-oj"]
        if self.language:
            cmd += ["-l", self.language]
        if self.diarize:
            cmd.append("-tdrz")
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            json_path = f"{audio_path}.json"
            if os.path.exists(json_path):
                with open(json_path) as f:
                    data = json.load(f)
                try:
                    os.remove(json_path)
                except OSError:
                    pass
                text = data.get("text", "")
                return {
                    "text": text.strip(),
                    "diarization": data,
                    "provider": "transcribe_cpp",
                }
            else:
                return {
                    "text": result.stdout.strip(),
                    "diarization": {},
                    "provider": "transcribe_cpp",
                }
        except subprocess.CalledProcessError as e:
            raise Exception(
                f"transcribe.cpp failed with return code {e.returncode}: {e.stderr}"
            ) from e


class TranscriptionService:
    """Service to handle transcription using a configured adapter."""

    def __init__(self, adapter: TranscriptionAdapter):
        self.adapter = adapter

    def transcribe_audio(self, audio_path: str) -> dict[str, Any]:
        return self.adapter.transcribe(audio_path)


def _turns_from_words(words: list[tuple[Any, str]]) -> list[tuple[str, str]]:
    turns: list[tuple[str, str]] = []
    for speaker, word in words:
        label = str(speaker) if speaker is not None else "0"
        if turns and turns[-1][0] == label:
            turns[-1] = (label, f"{turns[-1][1]} {word}")
        else:
            turns.append((label, word))
    return turns


def speaker_turns(result: dict[str, Any]) -> list[str]:
    """``"[Speaker N] text"`` lines, one per consecutive same-speaker turn.

    Reads each provider's diarization shape; falls back to one unlabeled
    ``[Speaker 0]`` line holding the whole transcript when there is none.
    """
    provider = result.get("provider")
    diarization = result.get("diarization")
    turns: list[tuple[str, str]] = []
    try:
        if provider == "assemblyai" and isinstance(diarization, list):
            turns = [
                (str(u.get("speaker", "?")), str(u.get("text", "")).strip())
                for u in diarization
                if str(u.get("text", "")).strip()
            ]
        elif provider == "deepgram" and isinstance(diarization, dict):
            words = diarization["results"]["channels"][0]["alternatives"][0].get("words", [])
            turns = _turns_from_words(
                [(w.get("speaker"), w.get("punctuated_word") or w.get("word", "")) for w in words]
            )
        elif provider == "speechmatics" and isinstance(diarization, dict):
            items: list[tuple[Any, str]] = []
            for r in diarization.get("results", []):
                alt = (r.get("alternatives") or [{}])[0]
                content = str(alt.get("content", ""))
                if r.get("type") == "punctuation" and items:
                    items[-1] = (items[-1][0], items[-1][1] + content)
                elif r.get("type") == "word":
                    speaker = str(alt.get("speaker", "S1")).lstrip("S") or "1"
                    items.append((speaker, content))
            turns = _turns_from_words(items)
        elif isinstance(diarization, dict) and isinstance(diarization.get("segments"), list):
            turns = [
                (str(seg.get("speaker", "0")), str(seg.get("text", "")).strip())
                for seg in diarization["segments"]
                if str(seg.get("text", "")).strip()
            ]
    except (KeyError, IndexError, TypeError, AttributeError):
        turns = []
    if not turns:
        text = str(result.get("text") or "").strip()
        return [f"[Speaker 0] {text}"] if text else []
    return [f"[Speaker {speaker}] {text}" for speaker, text in turns if text]


# ---------------------------------------------------------------------------
# Per-request provider choice
# ---------------------------------------------------------------------------

#: Provider id -> the env var holding its key (transcribe_cpp: its model path).
PROVIDER_ENV: dict[str, str] = {
    "speechmatics": "SPEECHMATICS_API_KEY",
    "assemblyai": "ASSEMBLYAI_API_KEY",
    "deepgram": "DEEPGRAM_API_KEY",
    "transcribe_cpp": TRANSCRIBE_CPP_MODEL_ENV,
}
PROVIDER_LABELS = {
    "speechmatics": "Speechmatics",
    "assemblyai": "AssemblyAI",
    "deepgram": "Deepgram",
    "transcribe_cpp": "Local transcribe_cpp",
}
PROVIDER_ADAPTERS: dict[str, type[TranscriptionAdapter]] = {
    "deepgram": DeepgramAdapter,
    "assemblyai": AssemblyAIAdapter,
    "speechmatics": SpeechmaticsAdapter,
    "transcribe_cpp": TranscribeCppAdapter,
}

#: ``.env`` / config keys for the ingest dialog defaults.
TRANSCRIBE_PROVIDER_ENV = "NOTEBOOKLM_TRANSCRIBE_PROVIDER"
LEGACY_TRANSCRIBE_PROVIDER_ENV = "NOTEBOOKLM_ASSESSMENT_TRANSCRIBE_PROVIDER"
TRANSCRIBE_DIARIZE_ENV = "NOTEBOOKLM_TRANSCRIBE_DIARIZE"
TRANSCRIBE_LANGUAGE_ENV = "NOTEBOOKLM_TRANSCRIBE_LANGUAGE"


@dataclass
class TranscriptionOptions:
    """Provider, diarization and language for one transcription request."""

    provider: str = "deepgram"
    diarize: bool = True
    #: ``None`` = auto-detect.
    language: str | None = None

    @classmethod
    def from_env(cls) -> TranscriptionOptions:
        provider = (
            os.environ.get(TRANSCRIBE_PROVIDER_ENV)
            or os.environ.get(LEGACY_TRANSCRIBE_PROVIDER_ENV)
            or "deepgram"
        ).lower()
        diarize = os.environ.get(TRANSCRIBE_DIARIZE_ENV, "true").strip().lower() not in (
            "0",
            "false",
            "no",
            "off",
        )
        language = os.environ.get(TRANSCRIBE_LANGUAGE_ENV, "auto").strip()
        return cls(
            provider=provider,
            diarize=diarize,
            language=None if language.lower() in ("", "auto") else language,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "diarize": self.diarize,
            "language": self.language or "auto",
        }


def key_present(provider: str) -> bool:
    env = PROVIDER_ENV.get(provider)
    return bool(env and os.environ.get(env, "").strip())


def providers() -> list[dict[str, Any]]:
    """Every provider with its env var and whether that env var is set."""
    return [
        {
            "id": pid,
            "label": PROVIDER_LABELS[pid],
            "env_var": env,
            "key_present": key_present(pid),
        }
        for pid, env in PROVIDER_ENV.items()
    ]


def build_adapter(options: TranscriptionOptions) -> TranscriptionAdapter:
    """Construct the chosen provider's adapter with the request's options."""
    cls = PROVIDER_ADAPTERS.get(options.provider)
    if cls is None:
        raise ValueError(
            f"Unknown transcription provider {options.provider!r}; "
            f"expected one of {sorted(PROVIDER_ADAPTERS)}"
        )
    return cls(diarize=options.diarize, language=options.language)  # type: ignore[call-arg]
