"""Look up CLI agent adapters by name and report which binaries are installed."""

from __future__ import annotations

import shutil
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .adapter import CLIAgentAdapter, Runner
from .agy import AgyAdapter
from .claude import ClaudeAdapter
from .opencode import OpenCodeAdapter
from .vibe import VibeAdapter

ADAPTERS: dict[str, type[CLIAgentAdapter]] = {
    cls.name: cls for cls in (ClaudeAdapter, AgyAdapter, VibeAdapter, OpenCodeAdapter)
}
AGENT_NAMES: tuple[str, ...] = tuple(ADAPTERS)


class UnknownAgentError(ValueError):
    """The requested agent name has no adapter."""


def get_adapter(name: str, **kwargs: Any) -> CLIAgentAdapter:
    """Instantiate the adapter registered as ``name`` (case-insensitive)."""
    key = name.strip().lower()
    try:
        cls = ADAPTERS[key]
    except KeyError:
        raise UnknownAgentError(
            f"unknown CLI agent {name!r}; expected one of {', '.join(AGENT_NAMES)}"
        ) from None
    return cls(**kwargs)


@dataclass(frozen=True)
class AgentStatus:
    name: str
    binary: str
    path: str | None
    version: str | None

    @property
    def available(self) -> bool:
        return self.path is not None


def agent_status(
    name: str,
    *,
    which: Callable[[str], str | None] = shutil.which,
    runner: Runner | None = None,
    probe_version: bool = True,
) -> AgentStatus:
    adapter = get_adapter(name, which=which, runner=runner)
    path = adapter.resolve()
    version = adapter.version() if path is not None and probe_version else None
    return AgentStatus(name=adapter.name, binary=adapter.binary_name, path=path, version=version)


def probe_agents(
    *,
    which: Callable[[str], str | None] = shutil.which,
    runner: Runner | None = None,
    probe_version: bool = True,
) -> list[AgentStatus]:
    """Status of every registered agent, in registry order."""
    return [
        agent_status(name, which=which, runner=runner, probe_version=probe_version)
        for name in AGENT_NAMES
    ]
