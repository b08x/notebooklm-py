"""Contract for running an LLM CLI coding agent headlessly and reading its JSON.

Each concrete adapter supplies two things: the argv that runs one prompt
non-interactively (:meth:`CLIAgentAdapter.build_argv`) and the extraction of the
assistant's text from that CLI's output envelope
(:meth:`CLIAgentAdapter.extract_text`). Process execution, timeouts, error
classification and JSON recovery are shared here.

The subprocess call is injected (``runner``) so tests never spawn a real agent.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, ClassVar

from .parser import JSONExtractionError, extract_and_repair_json

DEFAULT_TIMEOUT = 300.0
VERSION_TIMEOUT = 10.0


class AgentError(RuntimeError):
    """Base class for every CLI agent failure."""

    def __init__(self, agent: str, message: str) -> None:
        super().__init__(f"{agent}: {message}")
        self.agent = agent


class AgentNotFoundError(AgentError):
    """The agent binary is not on ``PATH``."""


class AgentTimeoutError(AgentError):
    """The agent did not finish within the timeout."""


class AgentCommandError(AgentError):
    """The agent exited non-zero or reported an error in its envelope."""

    def __init__(
        self, agent: str, message: str, *, returncode: int | None = None, stderr: str = ""
    ):
        super().__init__(agent, message)
        self.returncode = returncode
        self.stderr = stderr


class AgentParseError(AgentError):
    """The agent's output held no recoverable JSON payload."""


@dataclass(frozen=True)
class CompletedRun:
    returncode: int
    stdout: str
    stderr: str


Runner = Callable[[Sequence[str], float, Mapping[str, str] | None], CompletedRun]
"""``runner(argv, timeout, env) -> CompletedRun``; raises ``subprocess.TimeoutExpired``."""


def subprocess_runner(
    argv: Sequence[str], timeout: float, env: Mapping[str, str] | None = None
) -> CompletedRun:
    """Run ``argv`` with stdin closed (agents otherwise wait on, or block for, stdin)."""
    proc = subprocess.run(  # noqa: S603 - argv is built from a fixed adapter template
        list(argv),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=dict(env) if env is not None else None,
        check=False,
    )
    return CompletedRun(proc.returncode, proc.stdout or "", proc.stderr or "")


@dataclass(frozen=True)
class AgentResult:
    agent: str
    text: str
    """Assistant text extracted from the CLI envelope."""
    payload: Any
    """JSON value parsed from ``text`` (or the CLI's native structured output)."""
    stdout: str
    duration: float


class CLIAgentAdapter(ABC):
    """One headless invocation style of an LLM CLI coding agent."""

    name: ClassVar[str]
    binary: ClassVar[str]
    supports_schema: ClassVar[bool] = False

    def __init__(
        self,
        *,
        binary: str | None = None,
        model: str | None = None,
        agent: str | None = None,
        workdir: str | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        extra_args: Sequence[str] = (),
        env: Mapping[str, str] | None = None,
        runner: Runner | None = None,
        which: Callable[[str], str | None] = shutil.which,
    ) -> None:
        self.binary_name = binary or self.binary
        self.model = model
        #: Named agent/profile defined in the CLI's own config (``--agent NAME``).
        self.agent = agent or None
        #: Directory the CLI resolves project-local agents from (opencode, vibe).
        self.workdir = workdir or None
        self.timeout = timeout
        self.extra_args = tuple(extra_args)
        self.env = env
        self._runner = runner or subprocess_runner
        self._which = which

    # -- per-agent hooks -------------------------------------------------

    @abstractmethod
    def build_argv(
        self, executable: str, prompt: str, schema: Mapping[str, Any] | None
    ) -> list[str]:
        """argv that runs ``prompt`` once, non-interactively, with JSON output."""

    @abstractmethod
    def extract_text(self, stdout: str) -> str:
        """Assistant text from the CLI's output envelope.

        Raises :class:`AgentCommandError` when the envelope reports a failure
        and :class:`AgentParseError` when the envelope itself is unreadable.
        """

    def structured_payload(self, stdout: str) -> Any | None:
        """Native schema-validated output, when the CLI returns one separately."""
        return None

    # -- shared behaviour ------------------------------------------------

    def resolve(self) -> str | None:
        """Absolute path of the agent binary, or ``None`` when absent."""
        return self._which(self.binary_name)

    def available(self) -> bool:
        return self.resolve() is not None

    def version(self) -> str | None:
        """First line of ``<binary> --version``; ``None`` when unavailable."""
        executable = self.resolve()
        if executable is None:
            return None
        try:
            run = self._runner([executable, "--version"], VERSION_TIMEOUT, self._env())
        except (subprocess.TimeoutExpired, OSError):
            return None
        if run.returncode != 0:
            return None
        lines = (run.stdout or run.stderr).strip().splitlines()
        return lines[0].strip() if lines else None

    def stripped_env_vars(self) -> tuple[str, ...]:
        """Variables removed from the child environment (see ``ClaudeAdapter``)."""
        return ()

    def _env(self) -> dict[str, str] | None:
        """Child environment; ``None`` = inherit unchanged."""
        strip = [name for name in self.stripped_env_vars() if name in os.environ]
        if self.env is None and not strip:
            return None
        env = {k: v for k, v in os.environ.items() if k not in strip}
        return {**env, **(self.env or {})}

    def _execute(self, prompt: str, schema: Mapping[str, Any] | None) -> tuple[CompletedRun, float]:
        """Spawn the agent once; raise on a missing binary, timeout or non-zero exit."""
        executable = self.resolve()
        if executable is None:
            raise AgentNotFoundError(self.name, f"'{self.binary_name}' not found on PATH")
        argv = self.build_argv(executable, prompt, schema)
        started = time.monotonic()
        try:
            run = self._runner(argv, self.timeout, self._env())
        except subprocess.TimeoutExpired as exc:
            raise AgentTimeoutError(self.name, f"timed out after {self.timeout:g}s") from exc
        except OSError as exc:
            raise AgentCommandError(self.name, f"failed to start: {exc}") from exc
        duration = time.monotonic() - started
        if run.returncode != 0:
            detail = (run.stderr or run.stdout).strip().splitlines()
            tail = detail[-1] if detail else "no output"
            raise AgentCommandError(
                self.name,
                f"exited {run.returncode}: {tail}",
                returncode=run.returncode,
                stderr=run.stderr,
            )
        return run, duration

    def complete(self, prompt: str) -> str:
        """Run ``prompt`` and return the assistant text as-is (no JSON parsing)."""
        run, _ = self._execute(prompt, None)
        return self.extract_text(run.stdout)

    def run(self, prompt: str, *, schema: Mapping[str, Any] | None = None) -> AgentResult:
        """Run ``prompt`` and return the parsed JSON payload."""
        run, duration = self._execute(prompt, schema)
        structured = self.structured_payload(run.stdout)
        text = self.extract_text(run.stdout)
        if structured is not None:
            payload = structured
        else:
            try:
                payload = extract_and_repair_json(text)
            except JSONExtractionError as exc:
                raise AgentParseError(self.name, str(exc)) from exc
        return AgentResult(
            agent=self.name, text=text, payload=payload, stdout=run.stdout, duration=duration
        )


def load_envelope(agent: str, stdout: str) -> Any:
    """Parse a CLI's JSON envelope, tolerating preamble noise around it."""
    try:
        return extract_and_repair_json(stdout)
    except JSONExtractionError as exc:
        raise AgentParseError(agent, f"unreadable output envelope: {exc}") from exc
