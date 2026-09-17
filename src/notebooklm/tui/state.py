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


@dataclass
class TUIState:
    current_view: View = View.NOTEBOOK_LIST
    previous_view: View | None = None
    selected_notebook: str | None = None
    notebooks: list[Any] = field(default_factory=list)
    chat_history: list[dict[str, str]] = field(default_factory=list)
    chat_input: str = ""
    sort_key: str = "name"
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
