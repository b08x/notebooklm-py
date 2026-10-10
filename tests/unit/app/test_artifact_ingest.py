"""Artifact ingest: per-kind conversion, speaker turns, checksum gate (facts 51-57)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest
import soundfile as sf
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from notebooklm._app import artifact_ingest as ai
from notebooklm._app.corpus_explorer import CorpusFilters, browse, facets
from notebooklm._preprocessing import transcription as tr
from notebooklm.db.models import ChunkRun, Clause
from tests._fixtures.corpus_seed import Seeder, service
from tests._fixtures.postgres import pg_session  # noqa: F401

QUIZ = {
    "title": "Quiz",
    "questions": [
        {
            "question": "What limits memory?",
            "answerOptions": [{"text": "cgroups", "isCorrect": True}, {"text": "DNS"}],
            "hint": "kernel feature",
        }
    ],
}
CARDS = {"title": "Cards", "cards": [{"front": "OOM?", "back": "Out of memory"}]}
MIND = {"name": "Root", "children": [{"name": "Kernel", "children": [{"name": "cgroups"}]}]}
CSV = "name,value\nlimit,2G\nswap,0\n"


def _wav(path: str) -> None:
    """WAV bytes at any path (ffmpeg probes content, not the extension)."""
    t = np.arange(44100) / 44100
    sf.write(path, (0.1 * np.sin(2 * np.pi * 440 * t)).astype(np.float32), 44100, format="WAV")


class FakeArtifacts:
    def __init__(self, prefix: str) -> None:
        self.prefix = prefix
        self.items = {
            f"{prefix}-audio": ("audio", "Deep dive"),
            f"{prefix}-video": ("video", "Explainer"),
            f"{prefix}-report": ("report", "Briefing"),
            f"{prefix}-quiz": ("quiz", "Quiz"),
            f"{prefix}-cards": ("flashcards", "Cards"),
            f"{prefix}-mind": ("mind_map", "Map"),
            f"{prefix}-table": ("data_table", "Table"),
            f"{prefix}-info": ("infographic", "Poster"),
            f"{prefix}-slides": ("slide_deck", "Deck"),
        }
        self.report_text = "# Briefing\n\nKernel panics come from cgroup limits."
        self.downloads: list[str] = []

    def _art(self, aid: str) -> Any:
        kind, title = self.items[aid]
        return SimpleNamespace(id=aid, title=title, kind=kind, is_completed=True, created_at=None)

    async def list(self, nb: str) -> list[Any]:
        return [self._art(a) for a in self.items]

    async def get(self, nb: str, aid: str) -> Any:
        return self._art(aid)

    async def download_audio(self, nb: str, path: str, aid: str) -> str:
        self.downloads.append("audio")
        _wav(path)
        return path

    async def download_video(self, nb: str, path: str, aid: str) -> str:
        self.downloads.append("video")
        _wav(path)
        return path

    async def download_report(self, nb: str, path: str, aid: str) -> str:
        Path(path).write_text(self.report_text)
        return path

    async def download_quiz(self, nb: str, path: str, aid: str, output_format: str) -> str:
        assert output_format == "json"
        Path(path).write_text(json.dumps(QUIZ))
        return path

    async def download_flashcards(self, nb: str, path: str, aid: str, output_format: str) -> str:
        Path(path).write_text(json.dumps(CARDS))
        return path

    async def download_mind_map(self, nb: str, path: str, aid: str) -> str:
        Path(path).write_text(json.dumps(MIND))
        return path

    async def download_data_table(self, nb: str, path: str, aid: str) -> str:
        Path(path).write_text(CSV)
        return path


class Transcriber:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tr.TranscriptionOptions]] = []
        self.paths_exist: list[bool] = []

    def __call__(self, path: str, options: tr.TranscriptionOptions) -> dict[str, Any]:
        import soundfile

        info = soundfile.info(path)
        assert info.format == "FLAC" and info.channels == 1
        self.calls.append((path, options))
        return {
            "provider": "assemblyai",
            "text": "Hello there. Kernel panics hit limits.",
            "diarization": [
                {"speaker": "A", "text": "Hello there."},
                {"speaker": "B", "text": "Kernel panics hit limits."},
            ],
        }


@pytest.fixture
async def env(pg_session: AsyncSession, tmp_path: Path):  # noqa: F811
    s = Seeder(pg_session)
    client = SimpleNamespace(artifacts=FakeArtifacts(s.prefix))
    return SimpleNamespace(s=s, client=client, svc=service(), tmp=tmp_path)


async def _ingest(env: Any, suffix: str, **kw: Any) -> dict[str, Any]:
    kw.setdefault("cache_dir", None)
    return await ai.ingest_artifact(
        env.client, env.s.session, env.s.notebook, f"{env.s.prefix}-{suffix}", service=env.svc, **kw
    )


async def _texts(session: AsyncSession, doc: str) -> list[str]:
    rows = await session.execute(
        select(Clause.text)
        .join(ChunkRun, ChunkRun.id == Clause.run_id)
        .where(Clause.document_id == doc, ChunkRun.is_active.is_(True))
        .order_by(Clause.sentence_index)
    )
    return list(rows.scalars())


@pytest.mark.asyncio
async def test_list_ingestible_marks_image_kinds_disabled(env: Any) -> None:
    items = await ai.list_ingestible(env.client, env.s.notebook, env.s.session)
    by_kind = {i["kind"]: i for i in items}
    assert by_kind["infographic"]["ingestible"] is False
    assert by_kind["slide_deck"]["reason"] == "image-only, not ingestible yet"
    assert all(by_kind[k]["ingestible"] for k in ("audio", "video", "report", "quiz"))
    assert by_kind["audio"]["ingested"] is False
    with pytest.raises(ValueError, match="not ingestible"):
        await _ingest(env, "info")


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
@pytest.mark.asyncio
async def test_audio_ingest_flac_speaker_labels_and_checksum_gate(env: Any) -> None:
    trans = Transcriber()
    opts = tr.TranscriptionOptions("assemblyai", diarize=True, language=None)
    out = await _ingest(env, "audio", options=opts, transcriber=trans)
    assert out["status"] == "ingested" and out["n_children"] == 2
    doc = f"{env.s.prefix}-audio"
    assert await _texts(env.s.session, doc) == [
        "[Speaker A] Hello there.",
        "[Speaker B] Kernel panics hit limits.",
    ]
    flac_path, used = trans.calls[0]
    assert used.provider == "assemblyai" and not Path(flac_path).exists()  # temp FLAC deleted

    run = (
        await env.s.session.execute(select(ChunkRun).where(ChunkRun.document_id == doc))
    ).scalar_one()
    assert run.params["kind"] == "audio" and run.params["artifact_id"] == doc
    assert run.params["title"] == "Deep dive" and run.params["content_hash"] == out["content_hash"]

    again = await _ingest(env, "audio", options=opts, transcriber=trans)
    assert again["status"] == "skipped_unchanged" and len(trans.calls) == 1  # no paid call

    forced = await _ingest(env, "audio", options=opts, transcriber=trans, force=True)
    assert forced["status"] == "ingested" and len(trans.calls) == 2
    runs = (
        (await env.s.session.execute(select(ChunkRun).where(ChunkRun.document_id == doc)))
        .scalars()
        .all()
    )
    assert len(runs) == 2 and sum(r.is_active for r in runs) == 1
    assert next(r for r in runs if r.is_active).id == forced["run_id"]

    rows = await browse(
        env.s.session, CorpusFilters(notebook_ids=[env.s.notebook], kinds=["audio"])
    )
    assert rows["total"] == 2 and rows["items"][0]["kind"] == "audio"


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
@pytest.mark.asyncio
async def test_transcript_cache_reused_across_force(env: Any) -> None:
    trans = Transcriber()
    opts = tr.TranscriptionOptions("assemblyai")
    await _ingest(env, "video", options=opts, transcriber=trans, cache_dir=env.tmp)
    out = await _ingest(
        env, "video", options=opts, transcriber=trans, cache_dir=env.tmp, force=True
    )
    assert out["status"] == "ingested" and len(trans.calls) == 1


@pytest.mark.asyncio
async def test_text_kinds_convert_without_transcription(env: Any) -> None:
    trans = Transcriber()
    for suffix in ("report", "quiz", "cards", "mind", "table"):
        out = await _ingest(env, suffix, transcriber=trans)
        assert out["status"] == "ingested", suffix
    p = env.s.prefix
    assert trans.calls == []
    assert await _texts(env.s.session, f"{p}-quiz") == [
        "Q: What limits memory?\nA: cgroups\nHint: kernel feature"
    ]
    assert await _texts(env.s.session, f"{p}-cards") == ["Q: OOM?\nA: Out of memory"]
    assert await _texts(env.s.session, f"{p}-table") == [
        "name: limit | value: 2G",
        "name: swap | value: 0",
    ]
    mind = " ".join(await _texts(env.s.session, f"{p}-mind"))
    assert "- Root" in mind and "- Kernel" in mind and "- cgroups" in mind
    report = " ".join(await _texts(env.s.session, f"{p}-report"))
    assert "cgroup limits" in report

    # Unchanged report text is skipped; edited text re-ingests.
    assert (await _ingest(env, "report"))["status"] == "skipped_unchanged"
    env.client.artifacts.report_text += "\n\nNew paragraph."
    assert (await _ingest(env, "report"))["status"] == "ingested"

    f = await facets(env.s.session, CorpusFilters(notebook_ids=[env.s.notebook]))
    kinds = {i["value"] for i in f["kind"]}
    assert kinds == {"report", "quiz", "flashcards", "mind_map", "data_table"}


def test_converter_registry_and_helpers(tmp_path: Path) -> None:
    assert set(ai.CONVERTERS) == {
        "audio",
        "video",
        "report",
        "quiz",
        "flashcards",
        "mind_map",
        "data_table",
    }
    assert "infographic" not in ai.CONVERTERS and "slide_deck" not in ai.CONVERTERS
    empty = tmp_path / "e.csv"
    empty.write_text("\n")
    assert ai.data_table_to_chunks(str(empty)).chunks == []
    lines: list[str] = []
    ai._outline([{"title": "A", "children": [{"text": "B"}]}, "junk"], 0, lines)
    assert lines == ["- A", "  - B"]
    assert ai.artifact_kind(SimpleNamespace(kind=SimpleNamespace(value="audio"))) == "audio"


def test_speaker_turns_per_provider() -> None:
    dg = {
        "provider": "deepgram",
        "diarization": {
            "results": {
                "channels": [
                    {
                        "alternatives": [
                            {
                                "words": [
                                    {"speaker": 0, "punctuated_word": "Hi."},
                                    {"speaker": 0, "punctuated_word": "Yes."},
                                    {"speaker": 1, "punctuated_word": "No."},
                                ]
                            }
                        ]
                    }
                ]
            }
        },
    }
    assert tr.speaker_turns(dg) == ["[Speaker 0] Hi. Yes.", "[Speaker 1] No."]
    sm = {
        "provider": "speechmatics",
        "diarization": {
            "results": [
                {"type": "word", "alternatives": [{"content": "Hello", "speaker": "S1"}]},
                {"type": "punctuation", "alternatives": [{"content": "."}]},
                {"type": "word", "alternatives": [{"content": "Hey", "speaker": "S2"}]},
            ]
        },
    }
    assert tr.speaker_turns(sm) == ["[Speaker 1] Hello.", "[Speaker 2] Hey"]
    seg = {"provider": "x", "diarization": {"segments": [{"speaker": "0", "text": "a"}]}}
    assert tr.speaker_turns(seg) == ["[Speaker 0] a"]
    assert tr.speaker_turns({"provider": "transcribe_cpp", "text": "plain"}) == [
        "[Speaker 0] plain"
    ]
    assert tr.speaker_turns({"provider": "deepgram", "diarization": {"bad": 1}, "text": ""}) == []


def test_transcription_options_and_providers(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in (
        tr.TRANSCRIBE_PROVIDER_ENV,
        tr.LEGACY_TRANSCRIBE_PROVIDER_ENV,
        tr.TRANSCRIBE_DIARIZE_ENV,
        tr.TRANSCRIBE_LANGUAGE_ENV,
        "SPEECHMATICS_API_KEY",
    ):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv(tr.LEGACY_TRANSCRIBE_PROVIDER_ENV, "AssemblyAI")
    assert tr.TranscriptionOptions.from_env() == tr.TranscriptionOptions("assemblyai", True, None)
    monkeypatch.setenv(tr.TRANSCRIBE_PROVIDER_ENV, "speechmatics")
    monkeypatch.setenv(tr.TRANSCRIBE_DIARIZE_ENV, "false")
    monkeypatch.setenv(tr.TRANSCRIBE_LANGUAGE_ENV, "de")
    opts = tr.TranscriptionOptions.from_env()
    assert opts.to_dict() == {"provider": "speechmatics", "diarize": False, "language": "de"}
    monkeypatch.setenv("DEEPGRAM_API_KEY", "k")
    listed = {p["id"]: p for p in tr.providers()}
    assert listed["deepgram"]["key_present"] is True
    assert listed["speechmatics"] == {
        "id": "speechmatics",
        "label": "Speechmatics",
        "env_var": "SPEECHMATICS_API_KEY",
        "key_present": False,
    }
    adapter = tr.build_adapter(tr.TranscriptionOptions("deepgram", diarize=False, language=None))
    assert isinstance(adapter, tr.DeepgramAdapter) and adapter.language is None
    with pytest.raises(ValueError):
        tr.build_adapter(tr.TranscriptionOptions("nope"))
    with pytest.raises(ValueError, match="model_path"):
        tr.TranscribeCppAdapter().transcribe("x.flac")
    assert (
        tr.content_type_for("a.flac") == "audio/flac"
        and tr.content_type_for("a.bin") == "audio/mpeg"
    )
