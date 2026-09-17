import json
import os
import subprocess
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, Optional

import httpx


class TranscriptionAdapter(ABC):
    """Abstract base class for audio transcription adapters."""

    @abstractmethod
    def transcribe(self, audio_path: str) -> Dict[str, Any]:
        """
        Transcribe the audio file at the given path.

        Returns a dictionary containing at least:
        - 'text': the full transcribed text
        - 'diarization': optional diarization data if supported/requested
        """
        pass


class DeepgramAdapter(TranscriptionAdapter):
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.environ.get("DEEPGRAM_API_KEY")
        if not self.api_key:
            raise ValueError("Deepgram API key is required")

    def transcribe(self, audio_path: str) -> Dict[str, Any]:
        url = "https://api.deepgram.com/v1/listen?diarize=true"
        headers = {
            "Authorization": f"Token {self.api_key}",
            "Content-Type": "audio/mpeg",
        }
        with open(audio_path, "rb") as f:
            audio_data = f.read()

        with httpx.Client(timeout=300.0) as client:
            response = client.post(url, content=audio_data, headers=headers)
            response.raise_for_status()
            data = response.json()

            channels = data.get("results", {}).get("channels", [])
            text = channels[0].get("alternatives", [{}])[0].get("transcript", "") if channels else ""

            return {
                "text": text,
                "diarization": data,
                "provider": "deepgram",
            }


class AssemblyAIAdapter(TranscriptionAdapter):
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.environ.get("ASSEMBLYAI_API_KEY")
        if not self.api_key:
            raise ValueError("AssemblyAI API key is required")

    def transcribe(self, audio_path: str) -> Dict[str, Any]:
        headers = {"authorization": self.api_key}
        with httpx.Client(timeout=300.0) as client:
            with open(audio_path, "rb") as f:
                upload_resp = client.post(
                    "https://api.assemblyai.com/v2/upload", content=f, headers=headers
                )
                upload_resp.raise_for_status()
                audio_url = upload_resp.json()["upload_url"]

            transcript_req = {"audio_url": audio_url, "speaker_labels": True}
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
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.environ.get("SPEECHMATICS_API_KEY")
        if not self.api_key:
            raise ValueError("Speechmatics API key is required")

    def transcribe(self, audio_path: str) -> Dict[str, Any]:
        url = "https://asr.api.speechmatics.com/v2/jobs"
        headers = {"Authorization": f"Bearer {self.api_key}"}

        with httpx.Client(timeout=300.0) as client:
            config = {
                "type": "transcription",
                "transcription_config": {
                    "operating_point": "enhanced",
                    "language": "en",
                    "diarization": "speaker",
                },
            }
            with open(audio_path, "rb") as f:
                files = {
                    "data_file": (Path(audio_path).name, f, "audio/mpeg"),
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


class TranscribeCppAdapter(TranscriptionAdapter):
    def __init__(self, model_path: Optional[str] = None, executable_path: str = "main"):
        self.model_path = model_path
        self.executable_path = executable_path
        if not self.model_path:
            raise ValueError("model_path is required for transcribe.cpp")

    def transcribe(self, audio_path: str) -> Dict[str, Any]:
        cmd = [self.executable_path, "-m", self.model_path, "-f", audio_path, "-oj"]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            json_path = f"{audio_path}.json"
            if os.path.exists(json_path):
                with open(json_path, "r") as f:
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
            raise Exception(f"transcribe.cpp failed with return code {e.returncode}: {e.stderr}")


class TranscriptionService:
    """Service to handle transcription using a configured adapter."""

    def __init__(self, adapter: TranscriptionAdapter):
        self.adapter = adapter

    def transcribe_audio(self, audio_path: str) -> Dict[str, Any]:
        return self.adapter.transcribe(audio_path)

