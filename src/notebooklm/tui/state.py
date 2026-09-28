import concurrent.futures
from collections import deque
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any


class View(Enum):
    NOTEBOOK_LIST = auto()
    NOTEBOOK_DETAIL = auto()
    SOURCE_LIST = auto()
    ARTIFACT_LIST = auto()
    CHAT = auto()
    GENERATE = auto()
    COMPILER = auto()
    ASSESSMENT = auto()
    VISUAL_ASSESSMENT = auto()
    LOGS = auto()


SORT_MODES = ["name", "modified", "recent-artifacts"]
SORT_LABELS = {
    "name": "Alphabetical (A-Z)",
    "modified": "Recent Activity",
    "recent-artifacts": "Recent Artifacts",
}


@dataclass
class TUIState:
    current_view: View = View.NOTEBOOK_LIST
    previous_view: View | None = None
    selected_notebook: str | None = None
    notebooks: list[Any] = field(default_factory=list)
    chat_history: list[dict[str, str]] = field(default_factory=list)
    chat_input: str = ""
    sort_key: str = "name"
    searching: bool = False
    search_query: str = ""
    filter_has_audio: bool = False
    filter_min_sources: bool = False
    tui_cache: Any | None = None
    sidebar_focus: bool = True
    background_task: concurrent.futures.Future | None = None
    error_message: str | None = None
    compiler_state: dict[str, Any] = field(default_factory=dict)
    notebook_summaries: dict[str, str] = field(default_factory=dict)
    summary_task: concurrent.futures.Future | None = None
    stats_task: concurrent.futures.Future | None = None
    last_selection_time: float = 0.0
    detail_menu_index: int = 0
    scroll_offset: int = 0
    #: Notebook rows the sidebar fit on its last render; drives j/k paging.
    sidebar_rows: int = 15
    assessment_state: dict[str, Any] = field(default_factory=dict)
    editing_context: bool = False
    context_edit_buffer: str = ""
    context_overrides: dict[str, str] = field(default_factory=dict)
    log_records: deque = field(default_factory=lambda: deque(maxlen=500))
    selecting_sources: bool = False
    ingest_sources: list[Any] = field(default_factory=list)
    ingest_selected: set[str] = field(default_factory=set)
    ingest_completed: set[str] = field(default_factory=set)
    ingest_cursor: int = 0
    source_fetch_task: concurrent.futures.Future | None = None
    ingest_progress: dict[str, Any] = field(default_factory=dict)
    selecting_artifact: bool = False
    audio_artifacts: list[Any] = field(default_factory=list)
    artifact_cursor: int = 0
    notebook_stats: dict[str, dict] = field(default_factory=dict)
    download_progress: dict[str, Any] = field(default_factory=dict)

    api_tokens: float = 10.0
    api_max_tokens: int = 10
    api_last_update: float = 0.0
    download_dir: str | None = None
    _last_rendered_tokens: int = -1

    def update_tokens(self) -> None:
        import time

        if self.api_last_update == 0.0:
            self.api_last_update = time.time()
        now = time.time()
        elapsed = now - self.api_last_update
        self.api_tokens = min(
            float(self.api_max_tokens), self.api_tokens + elapsed * 0.5
        )  # Replenish 1 token per 2 seconds
        self.api_last_update = now

    def consume_token(self) -> bool:
        self.update_tokens()
        if self.api_tokens >= 1.0:
            self.api_tokens -= 1.0
            return True
        return False

    def cycle_sort(self) -> str:
        current = "modified" if self.sort_key == "recent-activity" else self.sort_key
        try:
            idx = SORT_MODES.index(current)
            next_idx = (idx + 1) % len(SORT_MODES)
        except ValueError:
            next_idx = 0
        self.sort_key = SORT_MODES[next_idx]
        return self.sort_key

    def get_filtered_and_sorted_notebooks(self) -> list[Any]:
        import datetime

        filtered = self.notebooks
        if self.search_query.strip():
            query = self.search_query.strip().lower()
            filtered = [
                nb
                for nb in filtered
                if query in getattr(nb, "title", "").lower()
                or query in getattr(nb, "id", "").lower()
            ]

        if self.filter_has_audio:
            filtered = [
                nb
                for nb in filtered
                if self.notebook_stats.get(getattr(nb, "id", ""), {}).get("has_audio", False)
            ]

        if self.filter_min_sources:
            filtered = [nb for nb in filtered if getattr(nb, "sources_count", 0) > 0]

        if self.sort_key == "name":
            return sorted(filtered, key=lambda nb: getattr(nb, "title", "").lower())
        elif self.sort_key in ("recent-activity", "modified"):
            return sorted(
                filtered,
                key=lambda nb: (
                    getattr(nb, "modified_at", None)
                    or getattr(nb, "created_at", None)
                    or datetime.datetime.min.replace(tzinfo=datetime.timezone.utc)
                ),
                reverse=True,
            )
        elif self.sort_key == "recent-artifacts":

            def _artifact_sort_key(nb: Any):
                stats = self.notebook_stats.get(getattr(nb, "id", ""), {})
                ts = stats.get("recent_generated_at")
                if ts is not None:
                    try:
                        return datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc)
                    except Exception:
                        pass
                return (
                    getattr(nb, "modified_at", None)
                    or getattr(nb, "created_at", None)
                    or datetime.datetime.min.replace(tzinfo=datetime.timezone.utc)
                )

            return sorted(filtered, key=_artifact_sort_key, reverse=True)
        elif self.sort_key == "created":
            return sorted(
                filtered,
                key=lambda nb: (
                    getattr(nb, "created_at", None)
                    or datetime.datetime.min.replace(tzinfo=datetime.timezone.utc)
                ),
                reverse=True,
            )

        return filtered
