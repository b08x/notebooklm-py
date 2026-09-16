import concurrent.futures
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
