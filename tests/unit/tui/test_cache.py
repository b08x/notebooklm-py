from datetime import datetime, timezone
from types import SimpleNamespace

from notebooklm.tui.cache import TUICache


def test_cache_initializes_empty_when_file_missing(tmp_path):
    cache_file = tmp_path / "tui_cache.json"
    cache = TUICache(cache_path=cache_file)
    assert cache.get_all_summaries() == {}
    assert cache.get_all_artifact_stats() == {}
    assert cache.get_summary("nb-1") is None
    assert cache.get_artifact_stats("nb-1") is None


def test_cache_save_and_retrieve_summary(tmp_path):
    cache_file = tmp_path / "tui_cache.json"
    cache = TUICache(cache_path=cache_file)

    cache.save_summary("nb-1", "A great notebook summary")
    assert cache.get_summary("nb-1") == "A great notebook summary"

    # Batch save
    cache.save_summaries({"nb-2": "Second summary", "nb-3": "Third summary"})
    assert cache.get_summary("nb-2") == "Second summary"
    assert cache.get_summary("nb-3") == "Third summary"


def test_cache_ignores_placeholder_summaries(tmp_path):
    cache_file = tmp_path / "tui_cache.json"
    cache = TUICache(cache_path=cache_file)

    cache.save_summary("nb-1", "Loading summary...")
    cache.save_summary("nb-2", "Paused: Waiting for API capacity...")
    cache.save_summary("nb-3", "Error loading summary")

    assert cache.get_summary("nb-1") is None
    assert cache.get_summary("nb-2") is None
    assert cache.get_summary("nb-3") is None


def test_cache_save_and_retrieve_artifacts(tmp_path):
    cache_file = tmp_path / "tui_cache.json"
    cache = TUICache(cache_path=cache_file)

    dt = datetime(2026, 9, 28, 12, 0, tzinfo=timezone.utc)
    raw_artifacts = [
        SimpleNamespace(id="art-1", kind="audio", title="Deep Dive Audio", created_at=dt),
        SimpleNamespace(id="art-2", kind="report", title="Study Guide", created_at=None),
        SimpleNamespace(id="art-3", kind="quiz", title="Quick Quiz", created_at=None),
    ]

    stats = cache.save_artifacts("nb-1", raw_artifacts)
    assert stats["total_artifacts"] == 3
    assert stats["has_audio"] is True
    assert stats["has_notes"] is True
    assert stats["counts"]["audio"] == 1
    assert stats["counts"]["report"] == 1
    assert stats["counts"]["quiz"] == 1
    assert stats["recent_generated_at"] == dt.timestamp()

    # Re-read
    loaded = cache.get_artifact_stats("nb-1")
    assert loaded is not None
    assert loaded["has_audio"] is True
    assert loaded["counts"]["audio"] == 1


def test_cache_migrates_legacy_format(tmp_path):
    cache_file = tmp_path / "tui_cache.json"
    # Legacy format was flat { "nb-1": "Summary 1", "nb-2": "Summary 2" }
    cache_file.write_text('{"nb-1": "Legacy Summary 1", "nb-2": "Legacy Summary 2"}')

    cache = TUICache(cache_path=cache_file)
    assert cache.get_summary("nb-1") == "Legacy Summary 1"
    assert cache.get_summary("nb-2") == "Legacy Summary 2"

    # Saving new data preserves migrated summaries
    cache.save_summary("nb-3", "New Summary 3")
    assert cache.get_summary("nb-1") == "Legacy Summary 1"
    assert cache.get_summary("nb-3") == "New Summary 3"


def test_cache_handles_corrupt_json(tmp_path):
    cache_file = tmp_path / "tui_cache.json"
    cache_file.write_text("{{corrupt json content...")

    cache = TUICache(cache_path=cache_file)
    assert cache.get_all_summaries() == {}
    assert cache.get_all_artifact_stats() == {}

    # Can recover by writing
    cache.save_summary("nb-1", "Fresh summary")
    assert cache.get_summary("nb-1") == "Fresh summary"
