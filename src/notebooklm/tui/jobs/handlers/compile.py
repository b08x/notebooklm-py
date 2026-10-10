"""``compile`` job handler: bind, fill, and compile an audio YAML for the Compiler view."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path

import dspy

from ...views.compiler_gen import run_compile
from ..runner import JobContext

CompileFn = Callable[..., Awaitable[None]]


async def run_compile_job(ctx: JobContext, *, compile_fn: CompileFn = run_compile) -> str:
    """Run the compile with the runner's LM and mirror phases into the job store."""
    if ctx.state is None:
        raise RuntimeError("compile job requires TUI state")
    project_file = Path(ctx.payload["project_file"])
    notebook_id = ctx.notebook_id or ""
    ctx.phase("compiling")
    await compile_fn(
        ctx.state,
        project_file,
        notebook_id,
        dspy.settings.lm,
        progress=ctx.phase,
        before_api=ctx.acquire_token,
    )
    warning = ctx.state.compiler_state.get("warning")
    return f"compiled {project_file.stem} ({warning or 'no warnings'})"


async def handle(ctx: JobContext) -> str | None:
    return await run_compile_job(ctx)
