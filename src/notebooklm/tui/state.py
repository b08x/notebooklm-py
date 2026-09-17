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
    ingest_cursor: int = 0
    source_fetch_task: concurrent.futures.Future | None = None
    ingest_progress: dict[str, Any] = field(default_factory=dict)
