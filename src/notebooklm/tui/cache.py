"""Persistent cache for NotebookLM TUI sessions.

Caches notebook summaries and discovered artifact metadata across sessions in
`~/.notebooklm/tui_cache.json` (or NOTEBOOKLM_HOME). Uses file-locking for
concurrency safety across CLI and TUI processes.
"""

from __future__ import annotations

import datetime
import json
import logging
from pathlib import Path
from typing import Any

from filelock import FileLock

from notebooklm.paths import get_home_dir

logger = logging.getLogger(__name__)

CACHE_VERSION = 1


def get_tui_cache_path() -> Path:
    """Return the absolute path to the TUI cache JSON file."""
    return get_home_dir() / "tui_cache.json"


class TUICache:
    """Thread-safe and process-safe cache manager for TUI session data."""

    def __init__(self, cache_path: Path | None = None) -> None:
        self.cache_path = cache_path or get_tui_cache_path()
        self.lock_path = self.cache_path.with_suffix(".lock")
        self._memory_cache: dict[str, Any] | None = None

    def _load_raw(self, reload: bool = False) -> dict[str, Any]:
        """Read and normalize cache contents under a file lock."""
        if not reload and self._memory_cache is not None:
            return self._memory_cache

        if not self.cache_path.exists():
            data: dict[str, Any] = {"version": CACHE_VERSION, "summaries": {}, "artifacts": {}}
            self._memory_cache = data
            return data

        try:
            with FileLock(str(self.lock_path), timeout=5):
                text = self.cache_path.read_text(encoding="utf-8")
                if not text.strip():
                    return {"version": CACHE_VERSION, "summaries": {}, "artifacts": {}}
                data = json.loads(text)
        except Exception as e:
            logger.warning("Failed to load TUI cache from %s: %s", self.cache_path, e)
            return {"version": CACHE_VERSION, "summaries": {}, "artifacts": {}}

        # Backward compatibility: legacy cache was a flat dict of {notebook_id: summary}
        if isinstance(data, dict):
            if "summaries" in data or "artifacts" in data:
                return {
                    "version": data.get("version", CACHE_VERSION),
                    "summaries": data.get("summaries", {})
                    if isinstance(data.get("summaries"), dict)
                    else {},
                    "artifacts": data.get("artifacts", {})
                    if isinstance(data.get("artifacts"), dict)
                    else {},
                }
            # Flat dict -> migrate to summaries
            return {
                "version": CACHE_VERSION,
                "summaries": {k: str(v) for k, v in data.items()},
                "artifacts": {},
            }

        return {"version": CACHE_VERSION, "summaries": {}, "artifacts": {}}

    def _save_raw(self, data: dict[str, Any]) -> None:
        """Write normalized cache contents under a file lock."""
        self._memory_cache = data
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            with FileLock(str(self.lock_path), timeout=5):
                temp_file = self.cache_path.with_suffix(".tmp")
                temp_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
                temp_file.replace(self.cache_path)
        except Exception as e:
            logger.warning("Failed to write TUI cache to %s: %s", self.cache_path, e)

    def get_summary(self, notebook_id: str) -> str | None:
        """Retrieve a cached summary for a notebook, or None."""
        data = self._load_raw()
        return data["summaries"].get(notebook_id)

    def get_all_summaries(self) -> dict[str, str]:
        """Retrieve all cached summaries."""
        return self._load_raw()["summaries"]

    def save_summary(self, notebook_id: str, summary: str) -> None:
        """Save a single summary to cache."""
        if (
            not summary
            or summary.startswith("Loading")
            or summary.startswith("Paused")
            or "Error loading" in summary
        ):
            return
        data = self._load_raw()
        data["summaries"][notebook_id] = summary
        self._save_raw(data)

    def save_summaries(self, summaries: dict[str, str]) -> None:
        """Save multiple summaries to cache."""
        valid = {
            k: v
            for k, v in summaries.items()
            if v
            and not v.startswith("Loading")
            and not v.startswith("Paused")
            and "Error loading" not in v
        }
        if not valid:
            return
        data = self._load_raw()
        data["summaries"].update(valid)
        self._save_raw(data)

    def get_artifact_stats(self, notebook_id: str) -> dict[str, Any] | None:
        """Get artifact stats dictionary for a notebook, or None."""
        data = self._load_raw()
        return data["artifacts"].get(notebook_id)

    def get_all_artifact_stats(self) -> dict[str, dict[str, Any]]:
        """Get all cached artifact statistics."""
        return self._load_raw()["artifacts"]

    def save_artifacts(self, notebook_id: str, raw_artifacts: list[Any]) -> dict[str, Any]:
        """Summarize and cache artifacts for a notebook."""
        counts: dict[str, int] = {}
        has_audio = False
        has_notes = False
        latest_ts: float | None = None
        artifact_records: list[dict[str, Any]] = []

        now = datetime.datetime.now(datetime.timezone.utc).timestamp()

        for art in raw_artifacts:
            raw_kind = getattr(art, "kind", "unknown")
            kind_str = (raw_kind.value if hasattr(raw_kind, "value") else str(raw_kind)).lower()
            counts[kind_str] = counts.get(kind_str, 0) + 1

            if kind_str in ("audio", "audio_overview"):
                has_audio = True
            elif kind_str in ("note", "report", "document"):
                has_notes = True

            # Created timestamp
            created_at = getattr(art, "created_at", None) or getattr(art, "modified_at", None)
            art_ts: float | None = None
            if isinstance(created_at, datetime.datetime):
                art_ts = created_at.timestamp()
            elif isinstance(created_at, (int, float)):
                art_ts = float(created_at)

            if art_ts is not None:
                if latest_ts is None or art_ts > latest_ts:
                    latest_ts = art_ts

            artifact_records.append(
                {
                    "id": getattr(art, "id", str(art)),
                    "kind": kind_str,
                    "title": getattr(art, "title", ""),
                    "timestamp": art_ts,
                }
            )

        stats: dict[str, Any] = {
            "counts": counts,
            "total_artifacts": len(raw_artifacts),
            "artifact_count": len(raw_artifacts),
            "artifact_types": [r["kind"] for r in artifact_records],
            "has_audio": has_audio,
            "has_notes": has_notes,
            "recent_generated_at": latest_ts,
            "updated_at": now,
            "artifacts": artifact_records,
        }

        data = self._load_raw()
        data["artifacts"][notebook_id] = stats
        self._save_raw(data)
        return stats
