"""Local corpus (Postgres) CLI commands — thin Click layer over ``_app.sfl_tagging``.

Commands:
    tag-sfl   Run SFL annotation over ingested clauses (DSPy or a CLI coding agent)
"""

from __future__ import annotations

from typing import Any

import click

from .._app.scope import Scope
from .._app.sfl_tagging import (
    DSPY_BACKEND,
    AmbiguousNotebookError,
    ParentOutcome,
    TagSFLReport,
    default_engine,
    resolve_backend,
    run_tag_sfl,
)
from .error_handler import exit_with_code, handle_errors, output_error
from .options import json_option, notebook_option
from .rendering import console, json_output_response
from .resolve import require_notebook
from .runtime import run_async

AGENT_CHOICES = ("dspy", "claude", "agy", "vibe", "opencode")


@click.group("corpus")
def corpus() -> None:
    """Operate on the local ingested corpus (Postgres).

    \b
    Examples:
      notebooklm corpus tag-sfl -n <notebook-id> --agent claude
      notebooklm corpus tag-sfl --document <doc-id> --no-batch --json
    """


def _report_json(report: TagSFLReport, scope: Scope) -> dict[str, Any]:
    return {
        "status": "ok" if report.failed == 0 else "partial",
        "backend": report.backend,
        "scope": {
            "notebook_id": scope.notebook_id,
            "document_ids": list(scope.document_ids),
            "run_ids": list(scope.run_ids),
            "external_ids": list(scope.external_ids),
            "parent_id": scope.parent_id,
        },
        "children": report.children,
        "parents": len(report.parents),
        "tagged": report.tagged,
        "failed": report.failed,
        "errors": [
            {"parent_index": p.parent_index, "failed": p.failed, "first_error": p.first_error}
            for p in report.parents
            if p.first_error is not None
        ],
    }


@corpus.command("tag-sfl")
@notebook_option
@click.option("--document", "document_ids", multiple=True, help="Corpus document ID (repeatable)")
@click.option("--run", "run_ids", multiple=True, type=int, help="Chunk run ID (repeatable)")
@click.option("--chunk", "external_ids", multiple=True, help="Chunk external ID (repeatable)")
@click.option("--parent", "parent_id", type=int, default=None, help="Restrict to one parent chunk")
@click.option(
    "--agent",
    type=click.Choice(AGENT_CHOICES, case_sensitive=False),
    default=None,
    help="SFL backend (default: $NOTEBOOKLM_SFL_BACKEND, else dspy)",
)
@click.option("--model", default=None, help="Model passed to the CLI agent")
@click.option(
    "--agent-profile",
    default=None,
    help="Named agent the CLI loads (default: $NOTEBOOKLM_SFL_AGENT_PROFILE, else "
    "sfl-annotator; '' = none)",
)
@click.option(
    "--agent-workdir",
    default=None,
    help="Directory opencode/vibe resolve project agents from "
    "(default: $NOTEBOOKLM_SFL_AGENT_WORKDIR)",
)
@click.option("--timeout", type=float, default=None, help="Per-invocation agent timeout (s)")
@click.option(
    "--batch/--no-batch",
    default=None,
    help="Send each parent chunk's clauses in one agent prompt (default: on)",
)
@click.option(
    "--fallback/--no-fallback",
    default=None,
    help="Fall back to the DSPy engine when the agent fails (default: on)",
)
@json_option
def tag_sfl(
    notebook_id: str | None,
    document_ids: tuple[str, ...],
    run_ids: tuple[int, ...],
    external_ids: tuple[str, ...],
    parent_id: int | None,
    agent: str | None,
    model: str | None,
    agent_profile: str | None,
    agent_workdir: str | None,
    timeout: float | None,
    batch: bool | None,
    fallback: bool | None,
    json_output: bool,
) -> None:
    """Tag ingested clauses with SFL mood, modality and tenor.

    Scope is the notebook unless --document, --run or --chunk is given.
    Results are committed per parent chunk.

    \b
    Examples:
      notebooklm corpus tag-sfl --agent claude
      notebooklm corpus tag-sfl -n <id> --agent opencode --model anthropic/claude-haiku-5-5
      notebooklm corpus tag-sfl --document <doc-id> --agent dspy --json
    """
    with handle_errors(json_output=json_output):
        _tag_sfl(
            notebook_id,
            document_ids,
            run_ids,
            external_ids,
            parent_id,
            agent,
            model,
            agent_profile,
            agent_workdir,
            timeout,
            batch,
            fallback,
            json_output,
        )


def _tag_sfl(
    notebook_id: str | None,
    document_ids: tuple[str, ...],
    run_ids: tuple[int, ...],
    external_ids: tuple[str, ...],
    parent_id: int | None,
    agent: str | None,
    model: str | None,
    agent_profile: str | None,
    agent_workdir: str | None,
    timeout: float | None,
    batch: bool | None,
    fallback: bool | None,
    json_output: bool,
) -> None:
    explicit = bool(document_ids or run_ids or external_ids)
    if not explicit:
        notebook_id = require_notebook(notebook_id)
    scope = Scope(
        notebook_id=notebook_id,
        document_ids=tuple(document_ids),
        run_ids=tuple(run_ids),
        external_ids=tuple(external_ids),
        parent_id=parent_id,
    )

    backend = resolve_backend(agent)
    try:
        engine = default_engine(
            backend,
            model=model,
            timeout=timeout,
            batch=batch,
            fallback=fallback,
            agent_profile=agent_profile,
            workdir=agent_workdir,
        )
    except ValueError as exc:
        output_error(str(exc), code="INVALID_BACKEND", json_output=json_output, exit_code=2)

    lm = None
    if backend == DSPY_BACKEND or getattr(engine, "fallback", False):
        from .._app.assessment import setup_dspy_router

        # Main thread only: workers bind this LM with dspy.context.
        lm, _ = setup_dspy_router()

    def on_parent(number: int, total: int, outcome: ParentOutcome) -> None:
        if json_output:
            return
        mark = "[green]✓[/green]" if outcome.first_error is None else "[yellow]![/yellow]"
        line = (
            f"{mark} parent {outcome.parent_index} ({number}/{total}): {outcome.children} clauses"
        )
        if outcome.first_error is not None:
            line += f", {outcome.failed} failed — {outcome.first_error}"
        console.print(line)

    from ..db.session import async_session_maker

    if not json_output:
        console.print(f"[dim]SFL backend: {backend}[/dim]")
    try:
        report = run_async(
            run_tag_sfl(
                scope,
                session_factory=async_session_maker,
                engine=engine,
                lm=lm,
                on_parent=on_parent,
            )
        )
    except AmbiguousNotebookError as exc:
        output_error(
            str(exc),
            code="AMBIGUOUS_ID",
            json_output=json_output,
            exit_code=1,
            extra={"candidates": exc.candidates},
            hint="Use a longer notebook ID prefix.",
        )

    if report.children == 0:
        output_error(
            "No ingested clauses in scope.",
            code="NO_CLAUSES",
            json_output=json_output,
            exit_code=1,
            hint="Ingest the notebook first (TUI ingest job or Corpus Explorer).",
        )

    if json_output:
        json_output_response(_report_json(report, scope))
    else:
        console.print(
            f"Tagged {report.tagged}/{report.children} clauses across "
            f"{len(report.parents)} parents ({report.failed} failed) with {report.backend}."
        )
    if report.tagged == 0:
        exit_with_code(1)
