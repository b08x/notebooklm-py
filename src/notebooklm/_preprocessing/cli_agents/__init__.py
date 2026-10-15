"""Run LLM CLI coding agents (claude, agy, vibe, opencode) headlessly for annotation."""

from .adapter import (
    AgentCommandError,
    AgentError,
    AgentNotFoundError,
    AgentParseError,
    AgentResult,
    AgentTimeoutError,
    CLIAgentAdapter,
    CompletedRun,
    subprocess_runner,
)
from .agy import AgyAdapter
from .claude import ClaudeAdapter
from .opencode import OpenCodeAdapter
from .parser import JSONExtractionError, extract_and_repair_json
from .registry import (
    ADAPTERS,
    AGENT_NAMES,
    AgentStatus,
    UnknownAgentError,
    agent_status,
    get_adapter,
    probe_agents,
)
from .sfl_engine import AgentSFLEngine
from .vibe import VibeAdapter

__all__ = [
    "ADAPTERS",
    "AGENT_NAMES",
    "AgentCommandError",
    "AgentError",
    "AgentNotFoundError",
    "AgentParseError",
    "AgentResult",
    "AgentSFLEngine",
    "AgentStatus",
    "AgentTimeoutError",
    "AgyAdapter",
    "CLIAgentAdapter",
    "ClaudeAdapter",
    "CompletedRun",
    "JSONExtractionError",
    "OpenCodeAdapter",
    "UnknownAgentError",
    "VibeAdapter",
    "agent_status",
    "extract_and_repair_json",
    "get_adapter",
    "probe_agents",
    "subprocess_runner",
]
